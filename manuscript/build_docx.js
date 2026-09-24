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
children.push(p("공공데이터는 같은 항목이 배포 세대마다 다른 표기로 제공되어, 분석마다 정제 코드를 새로 작성하게 만든다. 본 연구는 Bronze–Silver–Gold 계층과 명시적 Silver 계약을 갖춘 빌드 엔진을 구현하고, 서울시 아파트 실거래·전월세·따릉이 대여 3개 데이터셋(총 6,357,323행)에 적용해 세 가지를 측정했다. (1) 계약이 원천 표현의 무엇을 바꾸는가, (2) 계층을 저장하면 준비 코드와 재계산 비용이 어떻게 달라지는가, (3) 고정된 계약이 무엇을 재현하고 어디서 멈추는가. 계약은 데이터셋에 따라 역할 셀의 22.5~56.8%를 변경했고, 준비 코드는 Bronze 대비 Silver에서 40~32%, Gold에서 90~96% 줄었으며, 네 조건은 동일한 분석 결과에 도달했다. 10회 재빌드는 단일 다이제스트로 수렴했고, 의미를 파괴하는 변형 20건 중 12건은 거부됐으나 8건은 통과했다. 통과한 8건의 분해가 계약 언어의 현재 경계를 보여준다."));

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
children.push(p("준비 코드는 Bronze에서 Silver, Gold로 갈수록 단조 감소했다(T1: 20→12→2 LOC, T3: 50→34→2 LOC). monolithic은 Bronze와 비슷한 규모다(T1 16, T3 46). 네 조건 모두 동일한 output_hash를 산출해 equivalence gate를 통과했다."));
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
children.push(p("결과는 방향이 뚜렷하게 갈린다. 무효화가 분석이나 Gold에만 미치면 계층화가 빠르고(S1에서 최대 567배), Silver 이상이 무효화되면 오히려 느리다(0.48~0.72배). 후자는 계층화가 체크포인트를 쓰고 다시 읽는 비용을 추가로 치르기 때문이며, 이 방향은 4개 과제×엔진 셀과 5개 쌍 전부에서 동일했다. 즉 계층화의 이득은 재계산 빈도가 어디에 몰리는가에 달려 있다."));
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
children.push(p("통과한 8건의 분해가 이 실험의 핵심이다. 5건은 계약 언어가 표현할 수 있었으나 계약이 선언하지 않은 것이고, 3건만이 언어 자체의 한계다. 즉 무음 통과의 다수는 언어의 결함이 아니라 선언의 공백이며, 이는 도구가 아니라 계약 작성 관행으로 좁힐 수 있는 간격이다."));

// 4. Threats
children.push(h("4. 타당성 위협", HeadingLevel.HEADING_1));
children.push(p("T3의 조인 매칭률은 0.634로, 실거래와 전월세의 37%가 매칭되지 않았다. 원인은 두 원천의 단지명 표기 불일치이며, 계약은 단지명을 canonical 키로 정규화하지 않는다. 따라서 T3의 전세가율은 매칭된 부분집합에 대한 값이며, 서울시 전체를 대표하지 않는다."));
children.push(p("외부 공개 통계와의 대조는 수행하지 않았다. 전세가율은 분모(보증금/매매가)와 시점, 거래 필터를 어떻게 정의하느냐에 따라 값이 3.6%p 이동한다. 이 조건에서 대조를 수행하면 차이가 파이프라인에서 왔는지 정의에서 왔는지 분리할 수 없다."));
children.push(p("측정 대상은 서울시 3개 데이터셋과 2개 분석 과제로 한정된다. 다른 도메인·다른 배포 주기의 공공데이터로 일반화하려면 추가 측정이 필요하다. 인적 노력에 대한 주장은 하지 않는다 — LOC와 함수 수는 코드 규모의 지표이지 작성 난이도의 지표가 아니다."));

// 5. Conclusion
children.push(h("5. 결론 및 향후 과제", HeadingLevel.HEADING_1));
children.push(p("계약 기반 Medallion 파이프라인을 한국 공공데이터에 적용해, 표준화가 무엇을 바꾸는지, 계층 저장이 무엇을 주고받는지, 고정 계약이 어디서 멈추는지를 정량화했다. 계층화의 재계산 이득은 무조건적이지 않고 무효화 지점에 달려 있으며, 계약의 사각지대 8건 중 5건은 언어가 아니라 선언의 공백이었다."));
children.push(p("향후 과제는 세 가지다. (1) 단지명 정규화를 계약 언어에 포함해 T3 매칭률을 높이는 것, (2) 정의 민감도를 통제한 뒤 외부 통계와 대조하는 것, (3) 표현 불가로 분류된 3건을 계약 언어 확장의 요구사항으로 환원하는 것이다."));
children.push(rich([
  { t: "재현성. ", b: true },
  { t: "모든 측정값·스크립트·스냅샷 메타데이터는 공개 저장소에 있으며, 본문의 모든 숫자는 결과 파일에서 생성된 표에서 인용했다." },
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
