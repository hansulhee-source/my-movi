import datetime
import requests
import pandas as pd
import pytz
import streamlit as st


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
