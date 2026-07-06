#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
job-radar : 한국 채용 사이트의 신입 개발자 공고를 모아 신입 여부까지 자동 판정하는
            개인 학습용 CLI 도구.

수집 대상
  - 점핏 / 원티드 / 랠릿 : 프론트엔드가 호출하는 공개 JSON API를 직접 조회 → 경력 필드로 신입 여부 '정확' 판정
  - 잡코리아            : 공개 API가 없어 검색 페이지를 파싱하고, 상세페이지의 '경력 :' 필드로 신입 여부 판정

특징
  - 누적 중복제거 : 이전 실행에서 본 공고는 'NEW' 목록에서 제외 → 매번 새로 뜬 공고만 부각
  - 스케줄러 친화 : 표준 라이브러리만 사용(설치 불필요), 종료코드/로그 제공
  - --track backend | frontend 로 직무 전환

⚠️  개인 학습 / 포트폴리오 목적의 예제입니다. 각 사이트의 이용약관과 robots.txt를 존중하고,
    요청 사이에 간격(--sleep)을 두어 정중하게 호출하세요. 상업적·대량 수집 용도가 아닙니다.
    내부 엔드포인트는 사이트 사정에 따라 예고 없이 바뀔 수 있습니다.
"""
import argparse, urllib.request, urllib.parse, json, datetime, re, sys, io, os, time
import html as htmllib

try:  # 콘솔 한글 출력 보정 (Windows)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
TODAY = datetime.date.today()
NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# 직무별 설정 (스택/키워드/사이트별 카테고리)
TRACKS = {
    "backend": {
        "label": "백엔드/풀스택",
        "stack": {"java","spring","spring boot","kotlin","jpa","mybatis","querydsl",
                  "spring framework","spring mvc","nestjs"},
        "kw": ("백엔드","서버","backend","back-end","java","spring","kotlin","풀스택","full"),
        "jumpit": [(1,"백엔드"),(3,"풀스택")],
        "rallit": ("DEVELOPER_BACK_END","DEVELOPER_FULL_STACK"),
        "jk_queries": ("백엔드","자바 스프링","java"),
        "saramin": ("백엔드 신입 자바","자바 스프링 신입 개발자"),
        "strong": lambda s: ("spring" in s) and (("java" in s and "javascript" not in s.replace("java script","")) or "kotlin" in s),
        "strong_label": "Java+Spring",
    },
    "frontend": {
        "label": "프론트엔드/풀스택",
        "stack": {"react","react.js","next.js","nextjs","typescript","vue","vue.js","svelte",
                  "javascript","redux","zustand","tanstack query","react native","tailwind css"},
        "kw": ("프론트","frontend","front-end","풀스택","fullstack","full-stack","웹","react","vue","next"),
        "jumpit": [(2,"프론트"),(3,"풀스택")],
        "rallit": ("DEVELOPER_FRONT_END","DEVELOPER_FULL_STACK"),
        "jk_queries": ("프론트엔드","react","웹 개발자"),
        "saramin": ("프론트엔드 신입","react 신입 개발자"),
        "strong": lambda s: ("react" in s or "vue" in s or "next" in s) and ("typescript" in s or "react" in s),
        "strong_label": "React/Vue",
    },
}


# ---- 노이즈 필터 : 비개발 직무 · 모바일/프론트(백엔드 기준) · 시니어/경력 제외 ----
# 각 소스가 직무·경력을 완벽히 거르지 못해(특히 랠릿 API, 잡코리아/사람인 검색) 제목 기반으로 보정한다.
_MOBILE = ("안드로이드","android","ios","flutter","앱 개발","앱개발","react native","퍼블리","디자이너")
_SENIOR = ("시니어","senior","테크리드","tech lead","리드 개발","대리급","과장","차장",
           "5년","4년","3년 이상","경력 3","2~5","3~5","이상)")
_NONDEV = ("영업","컨설","마케팅","디자인","퍼블리","교육생","부트캠프","아카데미","강사","상담",
           "회계","인사","총무","금형","호텔","sm 모집","프로젝트 관리","관리업무","영업대표","생산",
           "품질","조리","시설","경영지원","사무","물류","기획자","텔레마","건축","전기공","기계설계",
           "간호","임상","약사","감리","devops","데브옵스","sre","qa 엔지니","qa엔지니","salesforce",
           "세일즈포스","pm 및")
def _has(title, words):
    t=(title or "").lower(); return any(w in t for w in words)
def is_mobile(title): return _has(title, _MOBILE)
def is_senior(title):
    if "신입" in (title or ""): return False   # '신입' 명시되면 유지
    return _has(title, _SENIOR)
def is_nondev(title): return _has(title, _NONDEV)
def rl_keep(cfg, title, skills):
    """랠릿 API의 filter.jobs가 부정확해 타 직무가 섞이므로 트랙 스택/키워드로 재필터한다."""
    if is_mobile(title) or is_senior(title): return False
    sks=[s.strip().lower() for s in (skills or [])]
    if sks: return any(s in cfg["stack"] for s in sks)          # 스킬 있으면 트랙 스택 요구
    tl=(title or "").lower()
    return any(k in tl or k in (title or "") for k in cfg["kw"])  # 없으면 트랙 키워드


def make_fetchers(sleep_sec):
    """요청 사이에 간격을 두는 정중한 fetch 함수 쌍을 만든다."""
    def get_json(u):
        time.sleep(sleep_sec)
        return json.load(urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=25))
    def get_text(u):
        time.sleep(sleep_sec)
        return urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html"}), timeout=25
        ).read().decode("utf-8", "replace")
    return get_json, get_text


# row = (site, newgrad_tag, company, title, stack, loc, deadline, url)

def collect_jumpit(cfg, get_json):
    rows = []
    def is_open(p):
        if p.get("alwaysOpen"): return True
        try: return datetime.date.fromisoformat(p.get("closedAt","")[:10]) >= TODAY
        except: return False
    def fit(p): return any(s.strip().lower() in cfg["stack"] for s in p.get("techStacks", []))
    def newtag(p): return "신입" if (p.get("newcomer") or p.get("minCareer",99)==0) else "~2년"
    for cat, label in cfg["jumpit"]:
        page=1; tot=1; seen=0
        while seen < tot and page <= 20:
            d=get_json(f"https://jumpit-api.saramin.co.kr/api/positions?jobCategory={cat}&sort=rsp_rate&page={page}")["result"]
            tot=d["totalCount"]; ps=d["positions"]
            if not ps: break
            seen+=len(ps); page+=1
            for p in ps:
                if is_open(p) and fit(p) and p.get("minCareer",99) <= 2:
                    dd="상시" if p.get("alwaysOpen") else p.get("closedAt","")[:10]
                    rows.append(("점핏", newtag(p), p["companyName"], f"[{label}] {p['title']}",
                                 "/".join(p.get("techStacks",[])[:7]), ",".join(p.get("locations",[])), dd,
                                 f"https://jumpit.saramin.co.kr/position/{p['id']}"))
    return rows


def collect_wanted(cfg, get_json):
    rows=[]
    for off in (0,100):
        u=(f"https://www.wanted.co.kr/api/v4/jobs?country=kr&tag_type_ids=518&years=0"
           f"&job_sort=job.latest_order&limit=100&offset={off}")
        d=get_json(u)
        for p in d.get("data",[]):
            if p.get("status")!="active": continue
            title=p.get("position") or p.get("title") or ""
            if not any(k in title.lower() or k in title for k in cfg["kw"]): continue
            if is_mobile(title) or is_senior(title): continue   # 모바일앱·시니어 컷
            comp=(p.get("company") or {}).get("name","")
            loc=""
            if isinstance(p.get("address"),dict):
                loc=",".join(p["address"].get("location","").split()[:2])
            rows.append(("원티드","신입",comp,title,"(상세확인)",loc,"상시/확인",
                         f"https://www.wanted.co.kr/wd/{p.get('id')}"))
        if not d.get("links",{}).get("next"): break
    return rows


def collect_rallit(cfg, get_json):
    rows=[]
    for jobs in cfg["rallit"]:
        u=("https://www.rallit.com/api/v1/position?"+urllib.parse.urlencode({
            "filter.jobGroup":"DEVELOPER","filter.jobs":jobs,"filter.careers":"NEWCOMER",
            "pageNumber":1,"pageSize":80}))
        d=get_json(u); data=d.get("data",d)
        items=data if isinstance(data,list) else (data.get("positions") or data.get("content") or data.get("items") or [])
        for p in items:
            comp=p.get("companyName") or (p.get("company") or {}).get("name","")
            title=p.get("title") or p.get("positionName") or ""
            skills=p.get("jobSkillKeywords") if isinstance(p.get("jobSkillKeywords"),list) else []
            if not rl_keep(cfg, title, skills): continue   # 타 직무·시니어 컷
            pid=p.get("id") or p.get("positionId")
            stack="/".join(skills[:6]) if skills else "(상세확인)"
            rows.append(("랠릿","신입",comp,title,stack,p.get("addressRegion","") or "",
                         p.get("endedAt","상시/확인") or "상시/확인",
                         f"https://www.rallit.com/positions/{pid}"))
    return rows


def collect_jobkorea(cfg, get_text):
    """잡코리아: 공개 API가 없어 검색 HTML을 파싱하고, 상세페이지 '경력 :' 필드로 신입 여부를 판정.
    경력 공고는 제외하고 신입/확인필요만 반환한다."""
    def career(gid):
        try:
            d=get_text(f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gid}")
            m=re.search(r"경력\s*:\s*([^,]+?)\s*,\s*학력", d)
            if not m: return ("확인필요","")
            c=m.group(1).strip()
            if "신입" in c: return ("신입", c)        # '신입' 또는 '신입·경력'
            if c.startswith("경력"): return ("경력", c)
            return ("확인필요", c)
        except Exception:
            return ("확인필요","")
    seen=set(); cand=[]
    for kw in cfg["jk_queries"]:
        raw=get_text("https://www.jobkorea.co.kr/Search/?stext="+urllib.parse.quote(kw))
        # 공고당 GI_Read 앵커가 (제목, 회사) 순서로 한 쌍씩 나온다
        anchors=re.findall(r'<a[^>]*GI_Read/(\d+)[^>]*>(.*?)</a>', raw, re.S)
        groups={}; order=[]
        for gid,inner in anchors:
            txt=htmllib.unescape(re.sub(r"<[^>]+>","",inner)).strip()
            if not txt or len(txt)<3: continue
            if gid not in groups: groups[gid]=[]; order.append(gid)
            groups[gid].append(txt)
        for gid in order:
            vals=groups[gid]; title=vals[0]; comp=vals[1] if len(vals)>1 else "(회사확인)"
            key=(comp,title[:30])
            if key in seen: continue
            if is_nondev(title) or is_mobile(title) or is_senior(title): continue  # 비개발·시니어 컷
            seen.add(key); cand.append((gid,comp,title))
    rows=[]
    for gid,comp,title in cand:
        tag,craw=career(gid)
        if tag=="경력": continue
        rows.append(("잡코리아",tag,comp,title,("경력:"+craw) if craw else "(상세확인)",
                     "(상세확인)","확인",f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gid}"))
    return rows


def collect_saramin(cfg, get_text):
    """사람인: 공개 API가 없어 검색 HTML을 파싱한다. 카드에서 (rec_idx, 제목, 회사)를 뽑고
    비개발/모바일/시니어 직무를 제외한다. (정확한 경력 여부는 상세페이지 확인 권장 → '신입/확인' 태그)"""
    rows=[]; seen=set()
    for kw in cfg.get("saramin", cfg["jk_queries"]):
        raw=get_text("https://www.saramin.co.kr/zf_user/search/recruit?searchType=search&searchword="
                     +urllib.parse.quote(kw))
        anchors=re.findall(r'class="job_tit"[^>]*>\s*(<a[^>]*>)', raw)
        comps=re.findall(r'class="corp_name"[^>]*>\s*<a[^>]*>([^<]+)</a>', raw)
        for i,a in enumerate(anchors):
            rid=re.search(r'rec_idx=(\d+)', a); tit=re.search(r'title="([^"]+)"', a)
            if not rid or not tit: continue
            gid=rid.group(1); title=htmllib.unescape(tit.group(1)).strip()
            comp=htmllib.unescape(comps[i]).strip() if i < len(comps) else "(회사확인)"
            key=(comp,title[:30])
            if key in seen: continue
            seen.add(key)
            if is_nondev(title) or is_mobile(title) or is_senior(title): continue
            tl=title.lower()
            if not (any(k in tl or k in title for k in cfg["kw"]) or "개발" in title or "engineer" in tl):
                continue   # 도메인 검색어의 비개발 노이즈 컷 (트랙 키워드/개발 신호 요구)
            rows.append(("사람인","신입/확인",comp,title,"(상세확인)","(상세확인)","확인",
                         f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={gid}"))
    return rows


def run(track, out_dir, prefer, sleep_sec):
    cfg=TRACKS[track]
    get_json, get_text = make_fetchers(sleep_sec)
    os.makedirs(out_dir, exist_ok=True)
    OUT  = os.path.join(out_dir, f"live_jobs_{track}.md")
    LOG  = os.path.join(out_dir, "monitor_log.txt")
    SEEN = os.path.join(out_dir, f"seen_urls_{track}.txt")

    status={}; rows=[]
    for name, fn, arg in [("점핏",collect_jumpit,get_json),("원티드",collect_wanted,get_json),
                          ("랠릿",collect_rallit,get_json),("잡코리아",collect_jobkorea,get_text),
                          ("사람인",collect_saramin,get_text)]:
        try:
            got=fn(cfg,arg); rows+=got; status[name]=f"OK({len(got)})"
        except Exception as e:
            status[name]=f"FAIL {e}"

    # 한 번 실행 내 중복제거 + 정렬
    _dk=set(); uniq=[]
    for r in rows:
        k=(r[2],r[3][:30])
        if k in _dk: continue
        _dk.add(k); uniq.append(r)
    def rank(r):
        site,ng,comp,title,st,loc,dd,url=r
        return (0 if prefer and prefer in loc else 1, 0 if cfg["strong"](st.lower()) else 1, 0 if site=="점핏" else 1)
    uniq.sort(key=rank)

    # 누적 중복제거: 이전에 본 적 없는 URL = 오늘 새 공고
    prev=set()
    if os.path.exists(SEEN):
        with open(SEEN,encoding="utf-8") as f:
            prev={ln.strip() for ln in f if ln.strip()}
    fresh=[r for r in uniq if r[7] not in prev]
    with open(SEEN,"w",encoding="utf-8") as f:
        f.write("\n".join(sorted(prev | {r[7] for r in uniq})))

    def line(r):
        site,ng,comp,title,st,loc,dd,url=r
        b=f"[{prefer}] " if (prefer and prefer in loc) else ""
        return f"- [{site}|{ng}] {b}**{comp}** - {title}\n  - {st} | {loc or '-'} | 마감:{dd} | {url}"

    pref_rows=[r for r in uniq if prefer and prefer in r[5]] if prefer else []
    strongr  =[r for r in uniq if cfg["strong"](r[4].lower()) and r not in pref_rows]
    rest     =[r for r in uniq if not cfg["strong"](r[4].lower()) and r not in pref_rows]

    with open(OUT,"w",encoding="utf-8") as f:
        f.write(f"# 라이브 채용 - {cfg['label']}\n\n")
        f.write(f"> **마지막 실행: {NOW}**  (이 줄의 시각이 오늘이면 정상 작동 중)\n")
        f.write("> "+" · ".join(f"{k}({v})" for k,v in status.items())
                +f" · 전체 {len(uniq)}건 / 🆕 오늘 새 공고 {len(fresh)}건\n")
        f.write("> 신입여부: 점핏/원티드/랠릿=API 경력필드(정확), 잡코리아=상세페이지 경력필드(정확) · 이전에 본 공고는 NEW에서 자동 제외\n\n")
        f.write(f"## 🆕 오늘 새로 뜬 공고 ({len(fresh)})\n"+("\n".join(map(line,fresh)) or "(오늘은 새 공고 없음)")+"\n\n")
        if prefer:
            f.write(f"## 📍 {prefer} 전체 ({len(pref_rows)})\n"+("\n".join(map(line,pref_rows)) or "(없음)")+"\n\n")
        f.write(f"## ★ {cfg['strong_label']} 강한 매칭 전체 ({len(strongr)})\n"+("\n".join(map(line,strongr)) or "(없음)")+"\n\n")
        f.write(f"## 그 외 전체 ({len(rest)})\n"+("\n".join(map(line,rest)) or "(없음)")+"\n")

    with open(LOG,"a",encoding="utf-8") as f:
        f.write(f"[{NOW}] {track} | "+" ".join(f"{k}:{v}" for k,v in status.items())
                +f" → 총 {len(uniq)}건 (새 {len(fresh)})\n")

    print(f"[{NOW}] {track} | "+" ".join(f"{k}:{v}" for k,v in status.items()))
    print(f"전체 {len(uniq)}건 / 오늘 새 공고 {len(fresh)}건")
    print("결과:", OUT)
    print("로그:", LOG)
    # 모든 소스가 실패하면 비정상 종료코드(스케줄러에서 감지용)
    return 0 if any(v.startswith("OK") for v in status.values()) else 1


def main():
    ap=argparse.ArgumentParser(description="한국 채용 사이트 신입 공고 모니터 (개인 학습용)")
    ap.add_argument("--track", choices=list(TRACKS), default="backend", help="직무 트랙 (기본: backend)")
    ap.add_argument("--out", default=os.environ.get("JOBRADAR_OUT", "./output"), help="결과 저장 폴더 (기본: ./output, 환경변수 JOBRADAR_OUT)")
    ap.add_argument("--prefer", default="", help="우선 표시할 지역명 (예: 부산). 비우면 지역 섹션 생략")
    ap.add_argument("--sleep", type=float, default=0.4, help="요청 사이 간격(초). 정중한 호출을 위해 권장 (기본: 0.4)")
    a=ap.parse_args()
    sys.exit(run(a.track, a.out, a.prefer, a.sleep))


if __name__ == "__main__":
    main()
