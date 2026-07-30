import json
import urllib.request
import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="대한민국 학령인구 지도",
    page_icon="🎒",
    layout="wide",
)

st.title("🎒 대한민국 시군구별 학령인구(중·고등학생) 지도")
st.write(
    "전국 읍·면·동 인구 데이터를 바탕으로 시군구별 **중학교(1~3학년)** 및 **고등학교(1~3학년)** 인구 현황과 **중3 vs 고1** 비교 분석을 제공합니다."
)


# ==========================================
# 2. 데이터 불러오기 및 캐싱 (속도 최적화)
# ==========================================
@st.cache_data
def load_data():
    # 1) 인구 데이터 (gzip 압축된 CSV 파일)
    pop_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
    df = pd.read_csv(pop_url, compression="gzip", dtype={"코드": str})

    # 2) 지도 경계 데이터 (GeoJSON 파일)
    geo_url = (
        "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
    )
    with urllib.request.urlopen(geo_url) as response:
        geojson = json.loads(response.read().decode("utf-8"))

    return df, geojson


# 데이터 로딩 실행
with st.spinner("데이터를 불러오고 있습니다. 잠시만 기다려주세요..."):
    df, geojson = load_data()


# ==========================================
# 3. 데이터 전처리 및 계산
# ==========================================
# 3-1. 가장 최신 연도 데이터 필터링
latest_year = df["연도"].max()
df_latest = df[df["연도"] == latest_year].copy()

# 3-2. 행정동 코드(10자리) 중 앞 5자리를 잘라 시군구 코드 생성
df_latest["sigungu_code"] = df_latest["코드"].str.slice(0, 5)


# 3-3. 나이별 인구 합산 함수
def get_age_columns(min_age, max_age=100):
    cols = []
    for age in range(min_age, max_age + 1):
        cols.append(f"계_{age}세")
    return [c for c in cols if c in df_latest.columns]


# 전체 인구 계산
all_age_cols = [c for c in df_latest.columns if c.startswith("계_") and ("세" in c)]
df_latest["총인구"] = df_latest[all_age_cols].sum(axis=1)

# 학령인구 정의 (한국 나이 기준 대략 매칭되는 만 나이 구간)
# 중학교 1~3학년: 만 12세 ~ 14세 ('계_12세' ~ '계_14세')
middle_school_cols = get_age_columns(12, 14)
df_latest["중학생_인구"] = df_latest[middle_school_cols].sum(axis=1)

# 고등학교 1~3학년: 만 15세 ~ 17세 ('계_15세' ~ '계_17세')
high_school_cols = get_age_columns(15, 17)
df_latest["고등학생_인구"] = df_latest[high_school_cols].sum(axis=1)

# 개별 학년 (중3 = 만 14세, 고1 = 만 15세)
df_latest["중3_인구"] = df_latest["계_14세"] if "계_14세" in df_latest.columns else 0
df_latest["고1_인구"] = df_latest["계_15세"] if "계_15세" in df_latest.columns else 0


# 3-4. GeoJSON 파일에서 시군구 코드와 이름(시도, 시군구) 매핑 정보 추출
geojson_meta = {}
for feature in geojson["features"]:
    props = feature["properties"]
    code = str(props.get("코드", ""))
    sigungu_name = props.get("시군구", "")
    sido_name = props.get("시도", "")
    if code:
        geojson_meta[code] = {"시도": sido_name, "시군구명": sigungu_name}


# 3-5. 시군구 코드별로 데이터 집계 (합산)
agg_dict = {
    "총인구": "sum",
    "중학생_인구": "sum",
    "고등학생_인구": "sum",
    "중3_인구": "sum",
    "고1_인구": "sum",
}

df_sigungu = df_latest.groupby("sigungu_code").agg(agg_dict).reset_index()

# GeoJSON의 정확한 시도 및 시군구명 매핑 적용
df_sigungu["시도"] = df_sigungu["sigungu_code"].map(
    lambda x: geojson_meta.get(x, {}).get("시도", "기타")
)
df_sigungu["시군구명"] = df_sigungu["sigungu_code"].map(
    lambda x: geojson_meta.get(x, {}).get("시군구명", x)
)


# 3-6. 비율 및 차이 계산
df_sigungu["중학생_비율"] = (df_sigungu["중학생_인구"] / df_sigungu["총인구"]) * 100
df_sigungu["고등학생_비율"] = (df_sigungu["고등학생_인구"] / df_sigungu["총인구"]) * 100

# 중3 vs 고1 인원 및 차이 (고1 - 중3)
df_sigungu["중고령_차이(고1-중3)"] = df_sigungu["고1_인구"] - df_sigungu["중3_인구"]


# ==========================================
# 4. 지도 색상 단계를 위한 구간 분류 (중학생 비율 기준)
# ==========================================
bins = [-float("inf"), 3.0, 5.0, 7.0, 10.0, float("inf")]
labels = ["3% 미만", "3%~5%", "5%~7%", "7%~10%", "10% 이상"]
df_sigungu["중학생비율구간"] = pd.cut(df_sigungu["중학생_비율"], bins=bins, labels=labels)


# ==========================================
# 5. Plotly 지도 시각화 (단계구분도)
# ==========================================
st.subheader(f"📍 대한민국 시군구별 중학생 인구 비율 지도 ({latest_year}년 기준)")

fig = px.choropleth(
    df_sigungu,
    geojson=geojson,
    locations="sigungu_code",  # 고유 '코드'로 지역 매칭
    featureidkey="properties.코드",  # GeoJSON 내부의 코드 속성
    color="중학생비율구간",
    color_discrete_map={
        "3% 미만": "#edf8fb",
        "3%~5%": "#b2e2e2",
        "5%~7%": "#66c2a4",
        "7%~10%": "#2ca25f",
        "10% 이상": "#006d2c",
    },
    category_orders={
        "중학생비율구간": ["3% 미만", "3%~5%", "5%~7%", "7%~10%", "10% 이상"]
    },
    hover_name="시군구명",
    hover_data={
        "시도": True,
        "중학생_비율": ":.2f",
        "고등학생_비율": ":.2f",
        "중3_인구": True,
        "고1_인구": True,
        "sigungu_code": False,
        "중학생비율구간": False,
    },
    labels={
        "중학생비율구간": "중학생 비율 구간",
        "시도": "시도",
        "중학생_비율": "중학생 비율(%)",
        "고등학생_비율": "고등학생 비율(%)",
        "중3_인구": "중3 인원(명)",
        "고1_인구": "고1 인원(명)",
    },
)

# 배경 지도 타일 없이 깔끔하게 경계선만 표시
fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    legend_title_text="중학생 비율 단계",
    height=650,
)

st.info("💡 **안내:** 마우스를 시군구 위에 올리면 **시군구 이름, 시도, 중학생/고등학생 비율, 중3 및 고1 인원 수**가 표시됩니다.")
st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 6. 지도 아래 순위 표 (중3 vs 고1 비교 중심)
# ==========================================
st.markdown("---")
st.subheader("📊 중학교 3학년 vs 고등학교 1학년 인원 비교 Top 10 / Bottom 10")
st.write("중3(만 14세) 인원과 고1(만 15세) 인원을 비교하여 학령인구 증감 추세를 살펴봅니다.")

df_sorted = df_sigungu.sort_values(by="중3_인구", ascending=False).reset_index(drop=True)

col_top, col_bottom = st.columns(2)

with col_top:
    st.markdown("#### 🔴 중3 인원 많은 곳 Top 10")
    top_10 = df_sorted.head(10)[["시도", "시군구명", "중3_인구", "고1_인구", "중고령_차이(고1-중3)", "총인구"]].copy()
    top_10.columns = ["시도", "시군구", "중3 인원", "고1 인원", "증감(고1-중3)", "총인구"]
    st.dataframe(top_10, use_container_width=True, hide_index=True)

with col_bottom:
    st.markdown("#### 🔵 중3 인원 적은 곳 Bottom 10")
    bottom_10 = df_sorted.tail(10).sort_values(by="중3_인구", ascending=True)[
        ["시도", "시군구명", "중3_인구", "고1_인구", "중고령_차이(고1-중3)", "총인구"]
    ].copy()
    bottom_10.columns = ["시도", "시군구", "중3 인원", "고1 인원", "증감(고1-중3)", "총인구"]
    st.dataframe(bottom_10, use_container_width=True, hide_index=True)


# ==========================================
# 7. 전국 학령인구 요약 비교 메트릭
# ==========================================
st.markdown("---")
st.subheader("📈 전국 중·고등학생 및 중3 vs 고1 총괄 요약")

total_middle_school = df_sigungu["중학생_인구"].sum()
total_high_school = df_sigungu["고등학생_인구"].sum()
total_m3 = df_sigungu["중3_인구"].sum()
total_h1 = df_sigungu["고1_인구"].sum()

m_col1, m_col2, m_col3, m_col4 = st.columns(4)
m_col1.metric("전국 중학생 (1~3학년)", f"{int(total_middle_school):,} 명")
m_col2.metric("전국 고등학생 (1~3학년)", f"{int(total_high_school):,} 명")
m_col3.metric("전국 중3 인원", f"{int(total_m3):,} 명")
m_col4.metric("전국 고1 인원", f"{int(total_h1):,} 명", f"{int(total_h1 - total_m3):,} 명")
