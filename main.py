import json
import urllib.request
import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="대한민국 고령화 및 학령인구 지도",
    page_icon="🗺️",
    layout="wide",
)

st.title("🗺️ 대한민국 시군구별 고령화 및 학령인구 지도")
st.write(
    "전국 읍·면·동 인구 데이터를 바탕으로 시군구별 65세 이상 인구 비율과 **중3(만 14세)·고1(만 15세)** 인구 현황을 비교 분석합니다."
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
    for age in range(min_age, max_age):
        cols.append(f"계_{age}세")
    if max_age >= 100:
        cols.append("계_100세 이상")
    return [c for c in cols if c in df_latest.columns]


# 전체 인구 및 65세 이상 인구 계산
all_age_cols = [c for c in df_latest.columns if c.startswith("계_") and ("세" in c)]
df_latest["총인구"] = df_latest[all_age_cols].sum(axis=1)

old_age_cols = get_age_columns(65, 100)
df_latest["65세이상_인구"] = df_latest[old_age_cols].sum(axis=1)

# 학령인구 정의: 중3 = 만 14세 ('계_14세'), 고1 = 만 15세 ('계_15세')
middle_school_col = "계_14세" if "계_14세" in df_latest.columns else None
high_school_col = "계_15세" if "계_15세" in df_latest.columns else None


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
agg_dict = {"총인구": "sum", "65세이상_인구": "sum"}
if middle_school_col and middle_school_col in df_latest.columns:
    agg_dict[middle_school_col] = "sum"
if high_school_col and high_school_col in df_latest.columns:
    agg_dict[high_school_col] = "sum"

df_sigungu = df_latest.groupby("sigungu_code").agg(agg_dict).reset_index()

# GeoJSON의 정확한 시도 및 시군구명 매핑 적용
df_sigungu["시도"] = df_sigungu["sigungu_code"].map(
    lambda x: geojson_meta.get(x, {}).get("시도", "기타")
)
df_sigungu["시군구명"] = df_sigungu["sigungu_code"].map(
    lambda x: geojson_meta.get(x, {}).get("시군구명", x)
)


# 3-6. 비율 계산 (고령화 비율, 중3 비율, 고1 비율 및 차이)
df_sigungu["고령화비율"] = (df_sigungu["65세이상_인구"] / df_sigungu["총인구"]) * 100

if middle_school_col and middle_school_col in df_sigungu.columns:
    df_sigungu["중3인원비율"] = (df_sigungu[middle_school_col] / df_sigungu["총인구"]) * 100
    df_sigungu["중3인원"] = df_sigungu[middle_school_col]
else:
    df_sigungu["중3인원비율"] = 0.0
    df_sigungu["중3인원"] = 0

if high_school_col and high_school_col in df_sigungu.columns:
    df_sigungu["고1인원비율"] = (df_sigungu[high_school_col] / df_sigungu["총인구"]) * 100
    df_sigungu["고1인원"] = df_sigungu[high_school_col]
else:
    df_sigungu["고1인원비율"] = 0.0
    df_sigungu["고1인원"] = 0

# 중3과 고1 인원 및 비율 차이 계산 (고1 - 중3)
df_sigungu["학령인구차이(고1-중3)"] = df_sigungu["고1인원"] - df_sigungu["중3인원"]
df_sigungu["학령인구비율차이(고1-중3)"] = df_sigungu["고1인원비율"] - df_sigungu["중3인원비율"]


# ==========================================
# 4. 5단계 구간 분류 설정 (고령화 비율 기준)
# ==========================================
# 경계값: 19% · 23% · 28% · 38%
bins = [-float("inf"), 19.0, 23.0, 28.0, 38.0, float("inf")]
labels = ["19% 미만", "19%~23%", "23%~28%", "28%~38%", "38% 이상"]
df_sigungu["고령화구간"] = pd.cut(df_sigungu["고령화비율"], bins=bins, labels=labels)


# ==========================================
# 5. Plotly 지도 시각화 (단계구분도)
# ==========================================
st.subheader(f"📍 대한민국 시군구별 고령화 지도 ({latest_year}년 기준)")

fig = px.choropleth(
    df_sigungu,
    geojson=geojson,
    locations="sigungu_code",  # 고유 '코드'로 지역 매칭
    featureidkey="properties.코드",  # GeoJSON 내부의 코드 속성
    color="고령화구간",
    color_discrete_map={
        "19% 미만": "#deebf7",
        "19%~23%": "#9ecae1",
        "23%~28%": "#4292c6",
        "28%~38%": "#08519c",
        "38% 이상": "#08306b",
    },
    category_orders={
        "고령화구간": ["19% 미만", "19%~23%", "23%~28%", "28%~38%", "38% 이상"]
    },
    hover_name="시군구명",
    hover_data={
        "시도": True,
        "고령화비율": ":.2f",
        "중3인원비율": ":.2f",
        "고1인원비율": ":.2f",
        "sigungu_code": False,
        "고령화구간": False,
    },
    labels={
        "고령화구간": "고령화 비율 구간",
        "시도": "시도",
        "고령화비율": "고령화 비율(%)",
        "중3인원비율": "중3 인원 비율(%)",
        "고1인원비율": "고1 인원 비율(%)",
    },
)

# 배경 지도 타일 없이 깔끔하게 경계선만 표시
fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    legend_title_text="고령화 비율 단계",
    height=650,
)

st.info("💡 **안내:** 마우스를 시군구 위에 올리면 **시군구 이름, 시도, 중3 인원(%), 고1 인원(%)**이 표시됩니다.")
st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 6. 지도 아래 순위 표 2개 (중3 기준 상위 10개 / 하위 10개)
# ==========================================
st.markdown("---")
st.subheader("📊 중학교 3학년 vs 고등학교 1학년 학령인구 비교 표")
st.write("중학교 3학년(만 14세) 인원 비율이 높은 곳과 낮은 곳의 **고1(만 15세)과의 차이**를 함께 비교합니다.")

df_sorted = df_sigungu.sort_values(by="중3인원비율", ascending=False).reset_index(drop=True)

col_top, col_bottom = st.columns(2)

with col_top:
    st.markdown("#### 🔴 중3 인원 비율 높은 곳 Top 10")
    top_10 = df_sorted.head(10)[["시도", "시군구명", "중3인원비율", "고1인원비율", "학령인구비율차이(고1-중3)", "총인구"]].copy()
    top_10.columns = ["시도", "시군구", "중3 비율(%)", "고1 비율(%)", "비율 차이(고1-중3)", "총인구"]
    top_10["중3 비율(%)"] = top_10["중3 비율(%)"].round(2)
    top_10["고1 비율(%)"] = top_10["고1 비율(%)"].round(2)
    top_10["비율 차이(고1-중3)"] = top_10["비율 차이(고1-중3)"].round(2)
    st.dataframe(top_10, use_container_width=True, hide_index=True)

with col_bottom:
    st.markdown("#### 🔵 중3 인원 비율 낮은 곳 Top 10")
    bottom_10 = df_sorted.tail(10).sort_values(by="중3인원비율", ascending=True)[
        ["시도", "시군구명", "중3인원비율", "고1인원비율", "학령인구비율차이(고1-중3)", "총인구"]
    ].copy()
    bottom_10.columns = ["시도", "시군구", "중3 비율(%)", "고1 비율(%)", "비율 차이(고1-중3)", "총인구"]
    bottom_10["중3 비율(%)"] = bottom_10["중3 비율(%)"].round(2)
    bottom_10["고1 비율(%)"] = bottom_10["고1 비율(%)"].round(2)
    bottom_10["비율 차이(고1-중3)"] = bottom_10["비율 차이(고1-중3)"].round(2)
    st.dataframe(bottom_10, use_container_width=True, hide_index=True)


# ==========================================
# 7. 전국 전체 학령인구 요약 비교 섹션
# ==========================================
st.markdown("---")
st.subheader("📈 전국 시군구 평균 학령인구(중3 vs 고1) 요약")

total_middle = df_sigungu["중3인원"].sum()
total_high = df_sigungu["고1인원"].sum()
total_pop = df_sigungu["총인구"].sum()

m_col1, m_col2, m_col3 = st.columns(3)
m_col1.metric("전국 총 중3 인원 (만 14세)", f"{int(total_middle):,} 명", f"전체 인구 대비 {(total_middle/total_pop)*100:.2f}%")
m_col2.metric("전국 총 고1 인원 (만 15세)", f"{int(total_high):,} 명", f"전체 인구 대비 {(total_high/total_pop)*100:.2f}%", delta_color="off")
diff_total = total_high - total_middle
m_col3.metric("고1 - 중3 인원 증감", f"{int(diff_total):,} 명", f"{'증가' if diff_total >= 0 else '감소'} 추세")
