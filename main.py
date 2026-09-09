import datetime
import requests
import pandas as pd
import pytz
import streamlit as st
import datetime
import requests
import pandas as pd
import pytz
import streamlit as st


# 1. API 데이터 요청 함수 (캐싱 적용: 1시간 동안 동일 날짜 요청 재사용)
@st.cache_data(ttl=3600)
def fetch_daily_boxoffice(api_key: str, target_date: str):
    """KOBIS API를 호출하여 해당 날짜의 박스오피스 데이터를 가져오는 함수"""
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": api_key, "targetDt": target_date}

    try:
        # API 요청 보내기 (타임아웃 10초 설정)
        response = requests.get(url, params=params, timeout=10)

        # HTTP 에러가 발생한 경우 예외 처리
        if response.status_code != 200:
            return None, f"서버 통신 오류가 발생했습니다. (상태 코드: {response.status_code})"

        data = response.json()

        # 인증키 오류 등 KOBIS API 자체 에러 처리 (faultInfo 확인)
        if "faultInfo" in data:
            error_message = data["faultInfo"].get("message", "알 수 없는 API 오류")
            return None, f"API 오류가 발생했습니다: {error_message}"

        # 정상 데이터 추출
        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        # 영화 목록이 비어있는 경우 "그날은 아직 집계 전입니다" 메시지 반환
        if not daily_list:
            return None, "그날은 아직 집계 전입니다."

        return daily_list, None

    except requests.exceptions.RequestException as e:
        # 네트워크 오류 등 예외 처리
        return None, f"네트워크 연결에 실패했습니다: {e}"


# --- Streamlit UI 구성 ---

# 페이지 기본 설정
st.set_page_config(page_title="일별 박스오피스 조회", page_icon="🎬", layout="wide")

st.title("🎬 박스오피스 조회 앱")

# 2. 한국 시간(KST) 기준 날짜 계산
try:
    kst_tz = pytz.timezone("Asia/Seoul")
    now_kst = datetime.datetime.now(kst_tz).date()
    yesterday = now_kst - datetime.timedelta(days=1)
except Exception as e:
    st.error(f"날짜 계산 중 오류가 발생했습니다: {e}")
    st.stop()

# 3. 달력(date_input)으로 날짜 선택 기능 추가 (최대 선택 가능 날짜는 '어제')
selected_date = st.date_input(
    "조회할 날짜를 선택하세요 (최대 어제까지 선택 가능):",
    value=yesterday,
    max_value=yesterday,
    min_value=datetime.date(2004, 1, 1),  # KOBIS 데이터 제공시점
)

# 선택된 날짜를 YYYYMMDD 포맷 및 읽기 쉬운 문자열로 변환
target_dt_str = selected_date.strftime("%Y%m%d")
formatted_date = selected_date.strftime("%Y년 %m월 %d일")
st.caption(f"선택한 일자: {formatted_date} (한국 시간 기준)")

# 4. Streamlit Secrets에서 API 키 가져오기
if "KOBIS_KEY" not in st.secrets:
    st.error(
        "❌ **API 키가 설정되지 않았습니다.**\n\n"
        "Streamlit Cloud의 App Settings > Secrets 메뉴에서 아래와 같이 인증키를 등록해주세요:\n\n"
        "
```toml\n"
        'KOBIS_KEY = "발급받은_KOBIS_키"\n'
        "
```"
    )
    st.stop()

kobis_key = st.secrets["KOBIS_KEY"]

# 5. 데이터 불러오기
with st.spinner("박스오피스 데이터를 불러오는 중입니다..."):
    raw_data, error_msg = fetch_daily_boxoffice(kobis_key, target_dt_str)

# 6. 에러 및 미집계 처리 안내 메시지
if error_msg:
    st.warning(f"⚠️ {error_msg}")
    st.info(
        "💡 **참고 안내:**\n"
        "1. 선택하신 날짜의 집계 데이터가 아직 생성되지 않았을 수 있습니다.\n"
        "2. API 키 설정(`KOBIS_KEY`)이 올바른지 확인해 보세요."
    )
    st.stop()

# 7. 데이터프레임 변환 및 수치형 변환
df = pd.DataFrame(raw_data)

# 수치형 컬럼 변환 (문자열 -> 숫자)
numeric_cols = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# 순위 기준으로 오름차순 정렬
df = df.sort_values(by="rank", ascending=True)


# 8. 순위 증감(rankInten) 및 누적관객 100만 이상(🏆) 가공
def format_rank_change(row):
    """순위 증감에 따라 빨간 위 화살표 / 파란 아래 화살표 / 신규 진입 등을 표시하는 함수"""
    inten = row["rankInten"]
    old_new = row.get("rankOldAndNew", "")

    if old_new == "NEW":
        return "🆕 NEW"
    elif inten > 0:
        return f"🔺 {int(inten)}"  # 순위 상승 (빨간 위 화살표)
    elif inten < 0:
        return f"🔻 {int(abs(inten))}"  # 순위 하강 (파란/아래 화살표)
    else:
        return "-"  # 변동 없음


df["순위변동"] = df.apply(format_rank_change, axis=1)

# 누적 관객 100만 명 이상 영화는 영화명 옆에 🏆 이모지 추가
df["표시_영화명"] = df.apply(
    lambda row: f"{row['movieNm']} 🏆" if row["audiAcc"] >= 1000000 else row["movieNm"],
    axis=1,
)

# 9. 1위 영화 지표 카드 (st.metric)
top_1 = df.iloc[0]

st.subheader(f"🥇 1위: {top_1['표시_영화명']}")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="해당 일자 관객수", value=f"{int(top_1['audiCnt']):,}명")

with col2:
    st.metric(label="누적 관객수", value=f"{int(top_1['audiAcc']):,}명")

with col3:
    st.metric(label="스크린수", value=f"{int(top_1['scrnCnt']):,}개")

st.divider()

# 10. 관객수 상위 5편 막대그래프
st.subheader("📊 상위 5개 영화 관객수 비교")

top_5_df = df.head(5)

# 차트 데이터 준비
chart_data = top_5_df[["표시_영화명", "audiCnt"]].copy()
chart_data.columns = ["영화명", "관객수"]
chart_data = chart_data.set_index("영화명")

st.bar_chart(chart_data)

st.divider()

# 11. 전체 박스오피스 순위 표
st.subheader("📋 전체 순위 목록")

# 표에 출력할 컬럼 정리
display_df = df[
    ["rank", "순위변동", "표시_영화명", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
].copy()
display_df.columns = [
    "순위",
    "변동",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]

# 숫자에 천 단위 쉼표(,) 및 서식 지정 후 출력
st.dataframe(
    display_df,
    use_container_width=True,
    column_config={
        "순위": st.column_config.NumberColumn(format="%d"),
        "변동": st.column_config.TextColumn(),
        "관객수": st.column_config.NumberColumn(format="%d명"),
        "누적관객": st.column_config.NumberColumn(format="%d명"),
        "스크린수": st.column_config.NumberColumn(format="%d개"),
    },
    hide_index=True,
)

# 1. API 데이터 요청 함수 (캐싱 적용: 1시간 동안 동일 요청 재사용)
@st.cache_data(ttl=3600)
def fetch_daily_boxoffice(api_key: str, target_date: str):
    """KOBIS API를 호출하여 해당 날짜의 박스오피스 데이터를 가져오는 함수"""
    url = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
    params = {"key": api_key, "targetDt": target_date}

    try:
        # API 요청 보내기 (타임아웃 10초 설정)
        response = requests.get(url, params=params, timeout=10)

        # HTTP 에러가 발생한 경우 예외 발생
        if response.status_code != 200:
            return None, f"서버 통신 오류가 발생했습니다. (상태 코드: {response.status_code})"

        data = response.json()

        # 인증키 오류 등 KOBIS API 자체 에러 처리 (faultInfo 확인)
        if "faultInfo" in data:
            error_message = data["faultInfo"].get(
                "message", "알 수 없는 API 오류"
            )
            return None, f"API 오류가 발생했습니다: {error_message}"

        # 정상 데이터 추출
        box_office_result = data.get("boxOfficeResult", {})
        daily_list = box_office_result.get("dailyBoxOfficeList", [])

        # 영화 목록이 비어있는 경우 처리
        if not daily_list:
            return None, "해당 날짜의 박스오피스 데이터가 비어 있습니다."

        return daily_list, None

    except requests.exceptions.RequestException as e:
        # 네트워크 오류 등 예외 처리
        return None, f"네트워크 연결에 실패했습니다: {e}"


# --- Streamlit UI 구성 ---

# 페이지 기본 설정
st.set_page_config(
    page_title="어제 박스오피스", page_icon="🎬", layout="wide"
)

st.title("🎬 어제의 일별 박스오피스")

# 2. 한국 시간(KST) 기준 어제 날짜 자동으로 구하기
try:
    kst_tz = pytz.timezone("Asia/Seoul")
    now_kst = datetime.datetime.now(kst_tz)
    yesterday = now_kst - datetime.timedelta(days=1)
    target_dt_str = yesterday.strftime("%Y%m%d")  # YYYYMMDD 형식
    formatted_date = yesterday.strftime("%Y년 %m월 %d일")
    st.caption(f"기준 일자: {formatted_date} (한국 시간)")
except Exception as e:
    st.error(f"날짜 계산 중 오류가 발생했습니다: {e}")
    st.stop()

# 3. Streamlit Secrets에서 API 키 가져오기
if "KOBIS_KEY" not in st.secrets:
    st.error(
        "❌ **API 키가 설정되지 않았습니다.**\n\n"
        "Streamlit Cloud의 App Settings > Secrets 메뉴에서 아래와 같이 인증키를 등록해주세요:\n\n"
        "```toml\n"
        'KOBIS_KEY = "발급받은_KOBIS_키"\n'
        "```"
    )
    st.stop()

kobis_key = st.secrets["KOBIS_KEY"]

# 4. 데이터 불러오기
with st.spinner("박스오피스 데이터를 불러오는 중입니다..."):
    raw_data, error_msg = fetch_daily_boxoffice(kobis_key, target_dt_str)

# 5. 에러 처리 및 안내 메시지
if error_msg:
    st.error(f"❌ **데이터를 불러오지 못했습니다.**\n\n{error_msg}")
    st.info(
        "💡 **확인해 보세요:**\n"
        "1. Streamlit Secrets에 입력한 `KOBIS_KEY`가 올바른지 확인하세요.\n"
        "2. 영화진흥위원회(KOBIS) 개발자센터에서 키 상태가 활성화되어 있는지 확인하세요.\n"
        "3. 인터넷 연결 상태나 서비스 서버 점검 여부를 확인해보세요."
    )
    st.stop()

# 6. 데이터프레임(Dataframe) 변환 및 데이터 타입 변경 (문자열 -> 숫자)
df = pd.DataFrame(raw_data)

# 수치형 컬럼 변환 (문자열을 숫자로 변환)
numeric_cols = [
    "rank",
    "rankInten",
    "audiCnt",
    "audiAcc",
    "scrnCnt",
    "showCnt",
]
for col in numeric_cols:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# 순위 기준으로 오름차순 정렬
df = df.sort_values(by="rank", ascending=True)

# 7. 1위 영화 지표 카드 ( st.metric )
top_1 = df.iloc[0]

st.subheader(f"🥇 1위: {top_1['movieNm']}")

col1, col2, col3 = st.columns(3)

with col1:
    # 당일 관객수
    st.metric(label="어제 관객수", value=f"{int(top_1['audiCnt']):,}명")

with col2:
    # 누적 관객수
    st.metric(label="누적 관객수", value=f"{int(top_1['audiAcc']):,}명")

with col3:
    # 스크린수
    st.metric(label="스크린수", value=f"{int(top_1['scrnCnt']):,}개")

st.divider()

# 8. 관객수 상위 5편 막대그래프
st.subheader("📊 상위 5개 영화 관객수 비교")

top_5_df = df.head(5)

# 차트용 데이터프레임 정리
chart_data = top_5_df[["movieNm", "audiCnt"]].copy()
chart_data.columns = ["영화명", "어제 관객수"]
chart_data = chart_data.set_index("영화명")

st.bar_chart(chart_data)

st.divider()

# 9. 전체 박스오피스 순위 표
st.subheader("📋 전체 순위 목록")

# 화면에 보여줄 컬럼선택 및 이름 변경
display_df = df[
    ["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
].copy()
display_df.columns = [
    "순위",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
]

# 숫자에 천 단위 쉼표(,) 서식 적용하여 출력
st.dataframe(
    display_df,
    use_container_width=True,
    column_config={
        "순위": st.column_config.NumberColumn(format="%d"),
        "관객수": st.column_config.NumberColumn(format="%d명"),
        "누적관객": st.column_config.NumberColumn(format="%d명"),
        "스크린수": st.column_config.NumberColumn(format="%d개"),
    },
    hide_index=True,
)
