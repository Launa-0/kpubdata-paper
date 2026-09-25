const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
} = require("docx");

const FONT = "함초롬바탕";
const BODY = 18;      // half-points → 9pt
const SMALL = 15;     // 7.5pt

const p = (text, opts = {}) =>
  new Paragraph({
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after === undefined ? 60 : opts.after, line: 240 },
    indent: opts.indent,
    children: [new TextRun({ text, font: FONT, size: opts.size || BODY, bold: opts.bold, italics: opts.italics })],
  });

const rich = (runs, opts = {}) =>
  new Paragraph({
    alignment: opts.align || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after === undefined ? 60 : opts.after, line: 240 },
    children: runs.map((r) =>
      new TextRun({ text: r.t, font: FONT, size: opts.size || BODY, bold: r.b, italics: r.i })),
  });

const h = (text, level) =>
  new Paragraph({
    spacing: { before: 160, after: 80 },
    children: [new TextRun({ text, font: FONT, size: BODY, bold: true })],
    heading: level || HeadingLevel.HEADING_2,
  });

// ---- tables -------------------------------------------------------------
const TABLE_W = 9360; // full text width in DXA

function table(headers, rows, widths) {
  const cw = widths || headers.map(() => Math.floor(TABLE_W / headers.length));
  const cell = (text, w, bold, shaded) =>
    new TableCell({
      width: { size: w, type: WidthType.DXA },
      shading: shaded ? { type: ShadingType.CLEAR, fill: "EFEFEF" } : undefined,
      margins: { top: 40, bottom: 40, left: 70, right: 70 },
      children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 0, line: 220 },
        children: [new TextRun({ text, font: FONT, size: SMALL, bold })],
      })],
    });

  return new Table({
    columnWidths: cw,
    width: { size: TABLE_W, type: WidthType.DXA },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((t, i) => cell(t, cw[i], true, true)),
      }),
      ...rows.map((r) => new TableRow({ children: r.map((t, i) => cell(String(t), cw[i])) })),
    ],
  });
}

const caption = (text) =>
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 120 },
    children: [new TextRun({ text, font: FONT, size: SMALL })],
  });

// ---- document -----------------------------------------------------------
const children = [];

// Title block
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 100 },
  children: [new TextRun({ text: "계약 기반 Medallion 파이프라인의 한국 공공데이터 적용에 대한 실증 평가", font: FONT, size: 30, bold: true })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 60 },
  children: [new TextRun({ text: "An Empirical Evaluation of a Contract-Driven Medallion Pipeline for Korean Public Data", font: FONT, size: 20, italics: true })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 40 },
  children: [new TextRun({ text: "[저자명]*, [저자명]**  ·  *[소속], **[소속]", font: FONT, size: BODY })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 200 },
  children: [new TextRun({ text: "e-mail: [이메일]  |  발표자: [발표자명]", font: FONT, size: SMALL })],
}));

// Abstract
children.push(h("요   약", HeadingLevel.HEADING_2));
children.push(p("공공데이터는 같은 항목이 배포 세대마다 다른 표기로 제공되어, 분석마다 정제 코드를 새로 작성하게 만든다. 본 연구는 Bronze–Silver–Gold 계층과 명시적 Silver 계약을 갖춘 빌드 엔진을 구현하고, 서울시 아파트 실거래·전월세·따릉이 대여 3개 데이터셋(총 6,357,323행)에 적용해 세 가지를 측정했다. (1) 계약이 원천 표현의 무엇을 바꾸는가, (2) 계층을 저장하면 준비 코드와 재계산 비용이 어떻게 달라지는가, (3) 고정된 계약이 무엇을 재현하고 어디서 멈추는가. 계약은 데이터셋에 따라 역할 셀의 22.5~56.8%를 변경했다. 준비 코드는 계측 행을 제외했을 때 Bronze 대비 Silver에서 30~31% 줄었고, 네 조건은 동일한 분석 결과에 도달했다. 재계산은 무효화 지점에 따라 갈려, 분석 수준에서는 계층화가 최대 568배 빨랐으나 Silver 이상이 무효화되면 0.48~0.72배로 느렸다. 10회 재빌드는 단일 다이제스트로 수렴했고, 의미를 파괴하는 변형 20건 중 12건은 거부·8건은 통과했으며, 의미를 보존하는 변형 31건 중에서도 4건의 오거부와 1건의 무음 손상이 나왔다."));

// 1. Introduction
children.push(h("1. 서론", HeadingLevel.HEADING_1));
children.push(p("공공데이터포털이 제공하는 데이터는 배포 세대가 바뀌면 컬럼명·결측 표기·식별자 자릿수가 함께 바뀐다. 분석자는 매번 그 차이를 흡수하는 코드를 새로 쓰고, 그 코드는 분석 스크립트 안에 섞여 재사용되지 않는다. 데이터 웨어하우스 영역에서 널리 쓰이는 Medallion 아키텍처(Bronze–Silver–Gold)는 이 문제를 계층 분리로 다루지만, 한국 공공데이터를 대상으로 그 효과를 정량적으로 측정한 연구는 드물다."));
children.push(p("본 연구는 계층화 자체가 아니라 계층 경계에 놓인 명시적 계약(contract)에 주목한다. Silver 계약은 원천 표현을 canonical 표현으로 옮기는 규칙을 선언으로 적는다. 본 연구의 기여는 다음과 같다."));
children.push(p("(1) 계약 기반 Bronze→Silver→Gold 빌드 엔진 구현 및 공개, (2) 3개 공공데이터셋에 대한 표준화·비용·재현성의 정량 평가, (3) 계약이 무엇을 잡고 무엇을 놓치는지에 대한 통제된 변형 실험.", { indent: { left: 200 } }));
children.push(rich([
  { t: "본 연구가 주장하지 않는 것" , b: true },
  { t: ". 계층화가 monolithic 스크립트보다 더 나은 변환을 만든다고 주장하지 않는다. 인적 노력을 줄인다고도 주장하지 않는다 — 사용자 실험은 수행하지 않았다." },
]));

// 2. Method
children.push(h("2. 실험 설계", HeadingLevel.HEADING_1));
children.push(p("세 데이터셋을 동결된 스냅샷으로 고정하고, 각 스냅샷에 대해 하나의 Silver 계약을 선언했다. 분석 과제는 T1(자치구×월 가격 집계·추세)과 T3(실거래·전월세 조인, 전세가율) 두 가지이며, 각각 Bronze / Silver / Gold / monolithic 네 조건에서 수행했다."));
children.push(caption("표 1. 데이터셋 범위"));
children.push(table(
  ["데이터셋", "기간", "원천 행 수", "용도"],
  [
    ["서울 아파트 실거래", "2020-01~2024-12", "233,596", "T1·T3, RQ1, R1, 변형"],
    ["서울 아파트 전월세", "2020-01~2024-12", "1,221,491", "T3, RQ1"],
    ["서울 따릉이 대여(통합)", "2020-01~2023-12", "4,902,236", "RQ1, R2"],
  ],
  [2600, 2200, 1800, 2760],
));
children.push(p("measurement의 전제는 네 조건이 같은 분석 결과에 도달한다는 것이다. 이를 output_hash 일치로 확인했으며, 이는 연구 질문이 아니라 비용 비교의 타당성 조건이다. 재계산 비용은 무효화 범위를 S1(분석 수준)부터 S4(원천 수준)까지 네 단계로 나누어, pandas와 polars 두 엔진에서 warm-up 1회 후 5회를 교차 측정했다."));
children.push(rich([
  { t: "준비 코드의 경계. ", b: true },
  { t: "어느 행이 \"준비\"인지를 사후에 판단하지 않기 위해, 각 조건은 prepare() 메서드를 구현하고 계측은 그 메서드와 전용 헬퍼만 센다. 분석 함수는 조건별로 두지 않고 하나를 모든 조건에 그대로 넘긴다. 다만 prepare() 안에는 단계 경계를 기록하는 계측 행(ctx.step)이 조건마다 0~7행 포함되며, 그 수는 변환 단계 수에 비례하므로 조건 간에 균일하지 않다. 따라서 3.2절은 원시 LOC와 계측 행을 뺀 LOC를 함께 보고한다." },
]));
children.push(p("통계는 기술 통계만 보고한다. 표본 구성상 추론 통계(p-값, 신뢰구간, 효과 크기)는 산출하지 않았다."));

// 3. Results
children.push(h("3. 결과", HeadingLevel.HEADING_1));

children.push(h("3.1 계약이 바꾸는 것", HeadingLevel.HEADING_2));
children.push(p("역할(role) 셀 단위로 Bronze와 Silver의 표현을 비교했다. 변경 원인은 결과를 보기 전에 규칙으로 고정했다."));
children.push(caption("표 2. 데이터셋별 표현 변경률과 주된 원인"));
children.push(table(
  ["데이터셋", "역할 셀", "변경 셀", "변경률", "주된 원인"],
  [
    ["실거래", "4,905,516", "1,168,608", "0.238", "타입 정규화, 수치 형식, 파생"],
    ["전월세", "21,986,838", "4,941,299", "0.225", "타입 정규화, 수치 형식, 파생"],
    ["따릉이", "53,924,596", "30,648,135", "0.568", "타입 정규화, 식별자 패딩, 연월·결측 정규화"],
  ],
  [1500, 1900, 1900, 1200, 2860],
));
children.push(p("따릉이의 변경률이 두 배 이상 높은 것은 이 데이터셋만 배포 세대가 다섯 번 바뀌었기 때문이다. 대여소 식별자 자릿수(2,241,547셀), 연월 표기(1,914,327셀), 결측 표기(1,991,589셀)가 세대마다 달라, 계약이 흡수해야 할 표면이 그만큼 넓다."));

children.push(h("3.2 계층을 저장하는 비용과 이득", HeadingLevel.HEADING_2));
children.push(p("네 조건 모두 동일한 output_hash를 산출해 equivalence gate를 통과했다. 준비 코드의 원시 LOC는 T1이 20→12→2, T3이 50→34→2로 계층을 올라갈수록 단조 감소했다. 그러나 이 수치에는 조건마다 다른 수의 계측 행이 섞여 있다. 계측 행을 빼면 Bronze→Silver 감소는 T1 13→9행(31%), T3 43→30행(30%)으로, 원시 값이 보여주던 40%·32%보다 작다."));
children.push(rich([
  { t: "두 가지를 감소로 읽어서는 안 된다. ", b: true },
  { t: "첫째, Gold의 2행은 성과가 아니라 정의다 — Gold는 분석 입력 형태로 미리 집계해 둔 계층이므로 준비 코드가 load 한 줄로 줄어드는 것은 동어반복이며, 집계 비용은 사라진 것이 아니라 빌드 시점으로 옮겨갔을 뿐이다. 둘째, monolithic은 원시 LOC로는 Bronze보다 작지만(T1 16 대 20, T3 46 대 50) 계측 행을 빼면 오히려 크거나 비슷하다(T1 15 대 13, T3 45 대 43). 즉 \"계층화가 monolithic보다 준비 코드를 줄인다\"는 결론은 이 측정으로 지지되지 않는다. 지지되는 것은 Bronze에서 Silver로 갈 때의 감소뿐이다." },
]));
children.push(caption("표 3. 재계산 시간의 쌍 비교 (비율 = monolithic ÷ materialized, 1보다 크면 계층화가 빠름)"));
children.push(table(
  ["과제·엔진", "S1 분석", "S2 Gold", "S3 Silver", "S4 원천"],
  [
    ["T1 · pandas", "41.4", "1.36", "0.53", "0.50"],
    ["T1 · polars", "8.67", "1.14", "0.48", "0.48"],
    ["T3 · pandas", "567.9", "1.48", "0.70", "0.72"],
    ["T3 · polars", "84.7", "1.24", "0.54", "0.53"],
  ],
  [2400, 1740, 1740, 1740, 1740],
));
children.push(p("결과는 방향이 뚜렷하게 갈린다. 무효화가 분석이나 Gold에만 미치면 계층화가 빠르고(S1에서 최대 568배), Silver 이상이 무효화되면 오히려 느리다(0.48~0.72배). 후자는 계층화가 체크포인트를 쓰고 다시 읽는 비용을 추가로 치르기 때문이며, 이 방향은 4개 과제×엔진 셀과 5개 쌍 전부에서 동일했다. 즉 계층화의 이득은 재계산 빈도가 어디에 몰리는가에 달려 있다."));
children.push(p("저장 비용은 같은 Parquet 조건에서 Bronze 대비 Silver가 0.92~0.99배였다. 두 계층을 모두 보관하면 약 1.93~1.99배가 된다."));

children.push(h("3.3 고정 계약이 재현하는 것과 멈추는 곳", HeadingLevel.HEADING_2));
children.push(p("동일 스냅샷·계약·빌더로 10회 재빌드한 결과 10회 모두 성공했고 다이제스트는 하나로 수렴했으며 canonical Silver와 바이트 단위로 일치했다."));
children.push(p("고정된 계약 하나로 따릉이 원천 세대 다섯을 빌드했을 때 G1·G2·I1·G3와 통합본은 행 손실 없이 통과했고, G4는 silver/coalesce 단계에서 fail-closed로 멈췄다. G4는 관측 단위 자체가 바뀐 세대다 — 계약이 조용히 잘못된 결과를 내는 대신 멈춘 것은 의도된 동작이다."));
children.push(caption("표 4. 의미 파괴 변형 20건에 대한 계약의 반응"));
children.push(table(
  ["계약 분류", "변형", "거부", "무음 통과"],
  [
    ["선언됨 / 포괄됨", "12", "12", "0"],
    ["표현 가능하나 미선언", "5", "0", "5"],
    ["현재 spec으로 표현 불가", "3", "0", "3"],
    ["합계", "20", "12", "8"],
  ],
  [3600, 1920, 1920, 1920],
));
children.push(p("통과한 8건 중 5건은 계약 언어가 표현할 수 있었으나 계약이 선언하지 않은 것이고, 3건은 현재 언어로 표현할 수 없는 것이다. 다만 이 분류는 저자가 사후에 부여한 것이며 \"표현 가능\"의 기준도 저자가 정했다. 따라서 이 분해는 도구의 성능이 아니라, 남은 간격 중 어디까지가 작성 관행의 문제이고 어디부터가 언어 확장의 요구사항인지를 가르는 진단으로만 읽어야 한다."));
children.push(rich([
  { t: "반대 방향의 오류. ", b: true },
  { t: "의미를 보존하는 변형 31건에서는 26건이 올바르게 수용됐으나, 4건은 잘못 거부됐고(silver의 tabularize 2건, cast 1건, zfill 1건) 1건은 값이 바뀐 채 통과했다(T-P10, 28,777셀). 오거부 4건은 계약이 원천의 정상적인 표기 변이를 과도하게 좁게 선언한 경우로, 운영에서는 멀쩡한 세대를 거부하는 비용으로 나타난다. 무음 손상 1건은 거부 실패 8건과 같은 성격의 사각지대다. 요약하면 이 계약은 51건 중 38건에서 옳았고, 13건에서 틀렸으며, 그 틀림은 양방향이다." },
]));

// 4. Threats
children.push(h("4. 타당성 위협", HeadingLevel.HEADING_1));
children.push(rich([
  { t: "구성 타당도. ", b: true },
  { t: "LOC는 개발 비용을 대표하지 않는다. 그래서 LOC 단독이 아니라 함수 수·변환 단계 수·실행 시간을 함께 보고했고, 3.2절에서 보듯 지표에 따라 결론이 달라진다 — 원시 LOC는 monolithic이 더 작다고, 계측 행을 뺀 LOC는 그렇지 않다고 말한다. 인적 노력에 대한 주장은 하지 않는다." },
]));
children.push(rich([
  { t: "내적 타당도. ", b: true },
  { t: "Gold가 분석의 답을 미리 담고 있으면 Gold에 유리한 실험이 된다. 이를 막기 위해 분석 함수는 조건별로 두지 않고 하나를 네 조건 모두에 그대로 넘겼으며, Gold에는 재사용 가능한 집계(자치구×월)까지만 두고 추세·전세가율 같은 최종 산출은 분석 함수에 남겼다. 그럼에도 Gold의 준비 코드 2행은 성과가 아니라 이 설계의 정의상 귀결이므로 감소 폭에서 제외해 읽어야 한다." },
]));
children.push(rich([
  { t: "기준선 편향. ", b: true },
  { t: "monolithic을 일부러 비효율적으로 구현하면 계층화가 유리해진다. 이를 막기 위해 monolithic은 특수 경로가 아니라 동일한 변환 헬퍼를 재사용하는 일반 조건으로 구현했고, 중간 산출을 저장하지 않는 것만이 차이다. 네 조건의 output_hash 일치가 이 동일성을 사후 검증한다." },
]));
children.push(rich([
  { t: "기준 통계 타당도. ", b: true },
  { t: "외부 공식 통계를 절대 기준으로 삼지 않았고, 대조 자체를 수행하지 않았다. 전세가율은 분모 정의·시점·거래 필터에 따라 값이 3.6%p 이동하므로, 대조를 하면 차이가 파이프라인에서 왔는지 정의에서 왔는지 분리할 수 없다. 또한 T3의 조인 매칭률은 0.634로 37%가 매칭되지 않았다 — 단지명 표기 불일치 때문이며 계약은 단지명을 canonical 키로 정규화하지 않는다. 따라서 T3의 값은 매칭된 부분집합에 대한 것이다." },
]));
children.push(rich([
  { t: "외적 타당도와 표본. ", b: true },
  { t: "측정은 서울시 3개 데이터셋, 2개 분석 과제, 1대의 장비에 한정된다. 시간 측정은 조건당 5쌍이고 warm-up 1회 뒤 교차 측정했으나, 표본이 작아 추론 통계는 산출하지 않고 쌍별 중앙값만 보고한다. S3·S4에서 관측된 역전은 4개 과제×엔진 셀과 5개 쌍 전부에서 방향이 같았다는 점까지가 근거이며, 그 크기는 장비에 의존한다. 사용자 실험은 수행하지 않았으므로 학습 비용·작성 난이도에 대한 결론은 이 연구의 범위 밖이다." },
]));

// 5. Conclusion
children.push(h("5. 결론 및 향후 과제", HeadingLevel.HEADING_1));
children.push(p("계약 기반 Medallion 파이프라인을 한국 공공데이터에 적용해, 표준화가 무엇을 바꾸는지, 계층 저장이 무엇을 주고받는지, 고정 계약이 어디서 멈추는지를 정량화했다. 세 결과 모두 조건부다. 준비 코드의 감소는 Bronze에서 Silver로 갈 때만 지지되고, 재계산 이득은 무효화가 분석·Gold에 머무를 때만 성립하며, 계약의 오류는 놓치는 쪽과 과도하게 막는 쪽 양방향으로 나타났다(51건 중 13건). 계층화가 무조건 낫다는 결론은 이 측정에서 나오지 않는다."));
children.push(p("향후 과제는 세 가지다. (1) 단지명 정규화를 계약 언어에 포함해 T3 매칭률을 높이는 것, (2) 정의 민감도를 통제한 뒤 외부 통계와 대조하는 것, (3) 표현 불가로 분류된 3건을 계약 언어 확장의 요구사항으로 환원하는 것이다."));
children.push(rich([
  { t: "재현성. ", b: true },
  { t: "본문의 모든 숫자는 동결된 결과 파일에서 생성된 표에서 인용했고, 결과 파일의 sha256은 빌더·논문 커밋 쌍에 묶여 검사된다. 측정값·실험 코드·계약·스냅샷 메타데이터는 공개 저장소에 있다. 스냅샷 바이트(Parquet 약 197MB)는 크기 때문에 저장소 밖에 별도 게시한다." },
]));

// References
children.push(h("참고문헌", HeadingLevel.HEADING_1));
children.push(p("[1] Databricks, \"What is a Medallion Architecture?\", 2022.", { size: SMALL, after: 20 }));
children.push(p("[2] 공공데이터포털, https://www.data.go.kr", { size: SMALL, after: 20 }));
children.push(p("[3] 서울 열린데이터광장, https://data.seoul.go.kr", { size: SMALL, after: 20 }));
children.push(p("[4] [빌더·실험 저장소 URL — 공개 후 기입]", { size: SMALL, after: 20 }));
children.push(p("[5] [Medallion/데이터 품질 관련 국내 선행연구 1~2편 보강 필요]", { size: SMALL, after: 20 }));

const doc = new Document({
  styles: {
    default: {
      document: { run: { font: FONT, size: BODY }, paragraph: { spacing: { line: 240 } } },
      heading1: { run: { font: FONT, size: 20, bold: true, color: "000000" }, paragraph: { spacing: { before: 180, after: 80 } } },
      heading2: { run: { font: FONT, size: BODY, bold: true, color: "000000" }, paragraph: { spacing: { before: 140, after: 60 } } },
    },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },          // A4
        margin: { top: 1130, bottom: 1130, left: 1270, right: 1270 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("ACK2026_medallion_draft.docx", buf);
  console.log("written", buf.length, "bytes");
});
