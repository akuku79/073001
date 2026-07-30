import json
import urllib.request
import pandas as pd
import plotly.express as px
import streamlit as st

# ==========================================
# 1. 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="대한민국 고령화 지도",
    page_icon="🗺️",
    layout="wide",
)

st.title("🗺️ 대한민국 시군구별 고령화 지도 (최신 연도)")
st.write(
    "전국 읍·면·동 인구 데이터를 바탕으로 시군구별 65세 이상 인구 비율을 계산하여 지도(단계구분도)로 보여드립니다."
)


# ==========================================
# 2. 데이터 불러오기 및 캐싱 (속도 향상)
# ==========================================
@st.cache_data
def load_data():
    # 인구 데이터 (gzip 압축된 CSV)
    pop_url = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
    df = pd.read_csv(pop_url, compression="gzip", dtype={"코드": str})

    # 지도 경계 데이터 (GeoJSON)
    geo_url = (
        "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"
    )
    with urllib.request.urlopen(geo_url) as response:
        geojson = json.loads(response.read().decode("utf-8"))

    return df, geojson


# 데이터 로딩 표시
with st.spinner("데이터를 불러오는 중입니다. 잠시만 기다려주세요..."):
    df, geojson = load_data()


# ==========================================
# 3. 데이터 전처리 및 계산
# ==========================================
# 3-1. 가장 최신 연도 선택
latest_year = df["연도"].max()
df_latest = df[df["연도"] == latest_year].copy()

# 3-2. 행정동 코드(10자리) 앞 5자리를 잘라 시군구 코드 생성
df_latest["sigungu_code"] = df_latest["코드"].str.slice(0, 5)


# 3-3. 65세 이상 인구 비율 계산 함수
# 나이별 열 이름 형식: '계_0세' ~ '계_100세 이상'
def get_age_columns(min_age, max_age=100):
    cols = []
    for age in range(min_age, max_age):
        cols.append(f"계_{age}세")
    if max_age >= 100:
        cols.append("계_100세 이상")
    return [c for c in cols if c in df_latest.columns]


# 전체 인구 열 확인 및 합계 계산
all_age_cols = [c for c in df_latest.columns if c.startswith("계_") and ("세" in c)]
df_latest["총인구"] = df_latest[all_age_cols].sum(axis=1)

# 65세 이상 인구 계산 (65세 ~ 100세 이상)
old_age_cols = get_age_columns(65, 100)
df_latest["65세이상_인구"] = df_latest[old_age_cols].sum(axis=1)

# [요청사항 반영] 중학교 3학년 인원(만 14세, 보통 15세 열 또는 나이 계산)
# 한국 나이/만 나이 기준 중3은 보통 만 14세 (0세부터 시작하므로 '계_14세')
middle_school_col = "계_14세" if "계_14세" in df_latest.columns else None


# 3-4. 시군구 단위로 그룹화 (합산)
group_dict = {"총인구": "sum", "65세이상_인구": "sum", "시도": "first", "동": "first"}
if middle_school_col and middle_school_col in df_latest.columns:
    group_dict[middle_school_col] = "sum"

df_sigungu = (
    df_latest.groupby("sigungu_code")
    .agg(group_dict)
    .reset_index()
)

# 시군구 이름 복원 (GeoJSON의 시군구 이름 또는 원본 데이터 시군구명 매핑)
# GeoJSON 파일에서 코드와 시군구 이름을 추출하여 매핑 테이블 생성
geojson_names = {}
for feature in geojson["features"]:
    props = feature["properties"]
    # 보통 '코드', '시군구', '시도' 속성이 들어있음
    code = str(props.get("코드", ""))
    name = props.get("시군구", "")
    if code:
        geojson_names[code] = name

# 시군구 이름 부여 (GeoJSON 기준 이름이 정확하므로 우선 매핑)
df_sigungu["시군구명"] = df_sigungu["sigungu_code"].map(geojson_names)

# 만약 매핑되지 않은 코드가 있다면 원본 데이터의 '동' 혹은 '시군구' 열 활용 보완 (여기서는 동에 시군구명이 포함되어 있거나 할 수 있음)
# 보통 제공되는 데이터 구조상 시군구명이 따로 없으면 원본에서 가져와야 하므로, 원본의 시군구 정보를 찾습니다.
if "시군구" in df.columns:
    # 원본에서 sigungu_code별 시군구 이름을 가져오는 맵 생성
    sigungu_name_map = df.drop_duplicates("sigungu_code").set_index("sigungu_code")["시군구"].to_dict()
    df_sigungu["시군구명"] = df_sigungu["시군구명"].fillna(df_sigungu["sigungu_code"].map(sigungu_name_map))

# 3-5. 65세 이상 인구 비율 (%) 계산
df_sigungu["고령화비율"] = (df_sigungu["65세이상_인구"] / df_sigungu["총인구"]) * 100

# 3-6. 중학교 3학년 인원 비율(%) 계산 (총인구 대비 또는 전체 인원 중 비율)
if middle_school_col and middle_school_col in df_sigungu.columns:
    df_sigungu["중3인원비율"] = (df_sigungu[middle_school_col] / df_sigungu["총인구"]) * 100
    df_sigungu["중3인원"] = df_sigungu[middle_school_col]
else:
    df_sigungu["중3인원비율"] = 0.0
    df_sigungu["중3인원"] = 0


# ==========================================
# 4. 5단계 구간 분류 (고령화 비율 기준)
# ==========================================
# 구간 경계값: 19% · 23% · 28% · 38%
# 범례 라벨: '19% 미만', '19% ~ 23%', '23% ~ 28%', '28% ~ 38%', '38% 이상'
bins = [-float("inf"), 19.0, 23.0, 28.0, 38.0, float("inf")]
labels = ["19% 미만", "19%~23%", "23%~28%", "28%~38%", "38% 이상"]
df_sigungu["고령화구간"] = pd.cut(df_sigungu["고령화비율"], bins=bins, labels=labels)


# ==========================================
# 5. Plotly 지도 시각화 (단계구분도)
# ==========================================
st.subheader(f"📍 대한민국 시군구별 고령화 현황 ({latest_year}년 기준)")

# 경남 진주 지역 강조를 위한 특별 처리 (진주시 코드 또는 이름 확인)
# 진주시의 코드를 찾거나 강조 표시에 활용
# 경남 진주의 경우 보통 코드가 '48170' 등으로 시작함
# 지도에서 특정 지역을 강조하기 위해 데이터에 강조 여부 컬럼 추가
df_sigungu["강조여부"] = df_sigungu["시군구명"].apply(lambda x: "진주시" if x == "진주시" else "기타")

fig = px.choropleth(
    df_sigungu,
    geojson=geojson,
    locations="sigungu_code",  # 지역 매칭은 '코드'로 진행
    featureidkey="properties.코드",  # GeoJSON 내의 코드 속성 경로
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
        "sigungu_code": False,
        "고령화구간": False,
    },
    labels={
        "고령화구간": "고령화 비율 구간",
        "시도": "시도",
        "고령화비율": "고령화 비율(%)",
        "중3인원비율": "중3 인원 비율(%)",
    },
)

# 지도 스타일 설정 (배경 지도 타일 없이 경계선만 보이도록 깔끔하게 조정)
fig.update_geos(fitbounds="locations", visible=False)
fig.update_layout(
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    legend_title_text="고령화 비율 단계",
    height=650,
)

# 마우스 툴팁 커스텀 및 진주 지역 안내 추가
st.info("💡 **안내:** 마우스를 시군구 위에 올리면 **시군구 이름, 시도, 중학교 3학년 인원(%)**이 표시됩니다. 경남 진주시는 지도에서 확인하실 수 있습니다!")
st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 6. 지도 아래 순위 표 2개 (상위 10개 / 하위 10개)
# ==========================================
st.markdown("---")
st.subheader("📊 중학교 3학년 인원 비율 기준 상·하위 시군구")

# 데이터 정렬 (중3 인원 비율 기준)
df_sorted = df_sigungu.sort_values(by="중3인원비율", ascending=False).reset_index(drop=True)

col_top, col_bottom = st.columns(2)

with col_top:
    st.markdown("#### 🔴 중3 인원 비율 높은 곳 Top 10")
    top_10 = df_sorted.head(10)[["시도", "시군구명", "중3인원비율", "총인구"]].copy()
    top_10.columns = ["시도", "시군구", "중3 인원 비율(%)", "총인구"]
    top_10["중3 인원 비율(%)"] = top_10["중3 인원 비율(%)"].round(2)
    st.dataframe(top_10, use_container_width=True, hide_index=True)

with col_bottom:
    st.markdown("#### 🔵 중3 인원 비율 낮은 곳 Top 10")
    bottom_10 = df_sorted.tail(10).sort_values(by="중3인원비율", ascending=True)[
        ["시도", "시군구명", "중3인원비율", "총인구"]
    ].copy()
    bottom_10.columns = ["시도", "시군구", "중3 인원 비율(%)", "총인구"]
    bottom_10["중3 인원 비율(%)"] = bottom_10["중3 인원 비율(%)"].round(2)
    st.dataframe(bottom_10, use_container_width=True, hide_index=True)


# ==========================================
# 7. 경남 진주 지역 요약 정보 카드 (강조 확인용)
# ==========================================
st.markdown("---")
st.subheader("🎯 경남 진주 지역 고령화 및 학생 현황")
jinju_data = df_sigungu[df_sigungu["시군구명"] == "진주시"]

if not jinju_data.empty:
    j_row = jinju_data.iloc[0]
    col_j1, col_j2, col_j3, col_j4 = st.columns(4)
    col_j1.metric("지역", f"{j_row['시도']} {j_row['시군구명']}")
    col_j2.metric("총 인구수", f"{int(j_row['총인구']):,} 명")
    col_j3.metric("고령화 비율 (65세 이상)", f"{j_row['고령화비율']:.2f}%")
    col_j4.metric("중3 인원 비율", f"{j_row['중3인원비율']:.2f}%")
else:
    st.warning("데이터에서 '진주시' 정보를 찾지 못했습니다.")
