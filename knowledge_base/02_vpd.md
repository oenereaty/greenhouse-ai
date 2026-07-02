---
crop: tomato
greenhouse_type: PO_film
variable: vpd_humidity
chunks:
  - section: 적정기준
    topic: vpd_management
    authority: Nongsaro, journal
    source_type: manual_and_paper
    use_for: threshold
    direct_control_rule: true
    reliability: high
    note: "RH 기준은 A등급(ASABE/농진청). VPD 수치는 B등급(논문 참고치). 직접 제어는 RH 기준 우선."
  - section: 조치원칙
    topic: vpd_management
    authority: RDA, journal
    source_type: manual_and_paper
    use_for: control_rule
    direct_control_rule: true
    reliability: high
    note: "VPD를 폐루프 제어 피드백으로 직접 사용하지 않는다. 온도·RH를 조정해 VPD를 간접 제어."
  - section: 생리근거
    topic: transpiration_stress
    authority: journal
    source_type: paper
    use_for: explanation
    direct_control_rule: false
    reliability: medium
    environment_type: greenhouse
---

## 적정기준

### VPD 개념

VPD(Vapour Pressure Deficit, 포차·수분부족분)는 현재 공기가 수증기를 더 받아들일 수 있는 여유 압력이다. 포화 수증기압(es)과 실제 수증기압(ed)의 차이로 계산하며, 단위는 kPa이다. 기온(℃)과 상대습도(RH, %)로 계산할 수 있다.

VPD가 0에 가까울수록 공기 중 습도가 높아 작물이 증산하기 어렵고, VPD가 클수록 공기가 건조해 작물에서 물을 빼앗아가는 힘이 강해진다. 상대습도보다 VPD가 실제 증산 환경을 더 정확하게 반영한다.

주의: VPD는 같은 값이 서로 다른 온도·습도 조합에서 나올 수 있다(예: VPD 0.85 kPa = 15℃·50% 또는 34℃·84%). 따라서 VPD 단일 값만으로 제어하면 실제 온실 상태를 잘못 판단할 수 있다. 제어는 반드시 온도와 RH를 함께 봐야 한다.

### 상대습도(RH) 적정 범위 — A등급 기준

ASABE(2015) 기준으로 온실 토마토의 적정 RH는 60~90%다. 전체 생육기 최적 범위는 50~70%이며, 화분(꽃가루) 수정은 RH 60% 내외에서 가장 잘 이루어진다. 농진청 고온기 관리 기준은 60~80% 유지를 권장한다.

RH 90% 초과: 화분이 열 스트레스에 취약해지고, 균류 병원균(회색곰팡이병·역병 등)이 빠르게 번진다. 배꼽썩음, 무름병 위험이 높아진다.

RH 50% 미만(건조): 잎이 말리고 증산 과다로 생육이 억제된다. 칼슘 이동이 원활하지 않아 배꼽썩음이 발생할 수 있다.

토마토는 비교적 건조한 공기에서 잘 자란다. 공중 습도가 높으면 회색곰팡이병·역병 발생이 많아진다.

### VPD 참고 범위 — B등급 논문 참고치

다수 논문에서 제시하는 온실 토마토 VPD 적정 범위:

| 구분 | VPD 범위 | 비고 |
|------|----------|------|
| 과습 위험 | < 0.3 kPa | 일액·곰팡이·무기물 결핍 위험 |
| 적정(보수적) | 0.5~0.8 kPa | Barker(1990), 대부분 온실작물 |
| 적정(실용) | 0.5~1.2 kPa | Argus(2009), 온실 제어 시스템 |
| 적정(넓은 범위) | 0.3~1.0 kPa | 복수 연구 공통 |
| 다소 높음 | 1.2~1.5 kPa | 증산 강함, 관수·환기 연동 필요 |
| 위험 | > 1.5 kPa | 위조·잎말림·생육정지 위험 |
| 병해 위험 | < 0.2 kPa | 병원균 확산 가속 |
| 생리장해 위험 | > 2.2 kPa | 생리장해·기공 폐쇄 위험 |

이 수치는 논문·제어시스템 참고치로, 농사로·농진청의 직접 제어 기준이 아니다. 진단 참고용으로만 사용하며, 제어 판단은 RH 기준(A등급)을 우선한다.

온도와 RH가 같을 때 기온이 오르면 VPD가 올라간다. 예: RH 75% 고정 시 기온 20℃→30℃ 이동하면 VPD는 약 0.58→1.06 kPa로 상승한다.

> 출처(RH 기준): ASABE Standard (2015), Heating, ventilating and cooling greenhouses; 농업인신문(2022), 농진청 고온기 토마토 관리 지침. authority=RDA/ASABE, use_for=threshold, direct_control_rule=true
> 출처(VPD 범위): Shamshiri et al. (2018) Table 2·3 요약; Barker(1990); Argus(2009). authority=journal, use_for=reference_only, direct_control_rule=false

---

## 조치원칙

### 핵심 원칙: VPD는 온도·RH를 통해 간접 제어

VPD를 직접 피드백 신호로 제어하지 않는다. 대신 온도를 낮추거나 RH를 높이는 방식으로 VPD를 간접적으로 낮추고, 온도를 높이거나 환기해 RH를 낮추는 방식으로 VPD를 간접적으로 높인다.

### VPD가 높을 때 (> 1.2~1.5 kPa, 건조·고온)

원인은 대개 고온 또는 저습(혹은 둘 다)이다.

온도 원인이 주된 경우: 차광 또는 환기로 기온을 먼저 낮춘다(→ 온도 변수 문서 참조). 기온이 낮아지면 포화 수증기압이 줄어 같은 절대습도에서도 VPD가 내려간다.

습도 원인이 주된 경우: 포그(안개 분무) 또는 미스트를 가동해 RH를 높인다. 포그 가동 시 VPD는 빠르게 낮아지지만 기온도 일부 낮아지므로 온도 모니터링을 함께 한다. 겨울철 포그를 이용한 VPD 제어 연구에서 VPD를 1.4→0.8 kPa로 낮췄을 때 순광합성률 상승과 생체중 17.3%, 수량 12.35% 증가가 보고된 바 있다.

포그 외 방법: 창문 개폐 최소화(환기 축소), 관수량 증가로 증발 면적 확보.

### VPD가 낮을 때 (< 0.3~0.4 kPa, 과습)

환기창을 열어 습한 공기를 외부로 내보낸다. 외기 습도가 낮은 시간대(오전~낮)를 활용한다. 난방을 약간 올려 온도를 높이면 포화 수증기압이 증가해 상대 VPD가 올라간다. 포그·미스트는 중단한다. 결로가 발생했거나 발생 직전이면 균류 병해 예방 조치를 함께 고려한다.

### CO2·환기와의 연계

환기를 열면 VPD가 올라가지만(외기가 건조한 경우) CO2가 희석된다. 반대로 환기를 닫고 포그를 가동하면 VPD는 낮아지지만 CO2 농도가 올라갈 수 있다. 세 변수(온도·VPD·CO2)는 환기 상태에서 서로 반대 방향으로 움직이는 경향이 있어, 한 변수만 보고 제어하면 다른 변수가 범위를 벗어날 수 있다(→ CO2·환기 변수 문서 참조).

> 출처: 농업인신문(2022), 농진청 고온기 토마토 관리 지침; Shamshiri et al. (2018); Lu et al. (2015), Control of VPD in greenhouse enhanced tomato growth, Scientia Horticulturae 197, 17-23. authority=RDA/journal, use_for=control_rule, direct_control_rule=true

---

## 생리근거

### VPD가 증산에 미치는 영향

VPD는 뿌리에서 잎으로 수분이 이동하는 주요 구동력이다. VPD가 높을수록 잎 표면의 수증기가 빠르게 날아가 증산이 증가하고, 뿌리가 이를 따라가지 못하면 수분 스트레스가 발생한다. 반대로 VPD가 0에 가까우면(es ≈ ed) 작물이 거의 증산하지 못해 칼슘·질소 등 수분 이동에 의존하는 양분의 흡수가 줄어든다.

VPD를 최적 수준으로 유지하면 시간당 수분 흡수량이 35~50% 증가하고, 800 mL/plant/day 수준의 흡수량 증가가 수량 향상으로 이어진다는 연구 결과가 있다.

### 낮은 VPD 장해 (< 0.3 kPa)

무기물 결핍(특히 칼슘), 일액 현상(guttation), 균류 병원균 확산, 연약 생장(잎·줄기가 크고 물러짐)이 나타난다. 과실이 빨리 물러지고 저장성이 낮아진다. 0.2 kPa 미만에서는 병원균 감염이 특히 심해진다. 저VPD에서 잎 면적과 줄기가 커지지만 뿌리 계통은 오히려 약해진다. 칼슘은 물관(xylem)을 통해 이동하므로 증산이 제한되면 칼슘 공급이 줄어 배꼽썩음이 발생한다.

### 높은 VPD 장해 (> 1.5 kPa)

위조(시들음), 잎말림, 생육 정지, 바삭한 잎 증상이 나타난다. 뿌리가 증산 수요를 따라가지 못하면 기공이 닫혀 광합성이 억제된다. 건조 지역에서 제어 없이 방치하면 VPD가 3~5 kPa에 달해 배꼽썩음·기공 폐쇄로 생산이 불가능해진다. 2.2 kPa를 초과하면 생리장해 위험이 크게 높아진다.

### 광량·온도와의 상호작용

일사량이 높으면 증산 수요가 커지고 칼슘이 잎에 과다 축적되어 과실의 칼슘이 부족해질 수 있다. 온도 상승은 포화 수증기압을 지수함수적으로 높여 같은 RH에서도 VPD를 급격히 올린다. 따라서 오전 일사 증가 구간에서 VPD 급등이 가장 빠르게 발생한다.

### 요약: VPD 단독 제어의 한계

VPD는 온도와 RH 모두에 달려 있어 같은 VPD 값이 완전히 다른 온실 상태에서 나올 수 있다. 예를 들어 VPD 0.85 kPa는 (15℃·50%) 또는 (34℃·84%)에서 동일하게 나타난다. 전자는 저온·저습으로 난방이 필요한 상태, 후자는 고온·고습으로 냉방·환기가 필요한 상태다. VPD 하나만 보고 포그를 켜거나 환기를 열면 잘못된 제어가 될 수 있다. 반드시 기온과 RH를 함께 확인하고, VPD는 진단 보조 지표로 활용한다.

이 내용은 고온·건조 또는 과습이 "왜" 위험한지를 설명하는 생리적 근거이며, 온실 제어의 직접 임계값으로 사용하지 않는다.

> 출처: Shamshiri et al. (2018), Int. Agrophys. 32, 287-302; Barker (1990), J. Horticultural Sci. 65(3), 323-331; Lu et al. (2015), Scientia Horticulturae 197, 17-23. authority=journal, use_for=explanation, direct_control_rule=false
