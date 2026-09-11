/**
 * ledDemoFixture.ts
 *
 * Centralized fixture for the Municipal LED Street Lighting demo analysis.
 * Activated when the backend response bears the tender title containing
 * "MCD-2024-LT-09" (set by NewAnalysisPage when the sample button is pressed).
 *
 * All other analyses use the real pipeline unchanged.
 *
 * Standards chosen are coherent and all exist in the project catalogue:
 *  • IS 16107       — LED road/street luminaire performance (primary)
 *  • IS 10322 P5S3  — Luminaires for road and street lighting (safety/construction)
 *  • IS 10322 P1    — Luminaires general requirements and tests
 *  • IS 16106       — Photometric measurement methods for LED products (testing)
 *  • IS 1944 P1&2   — Code of practice for lighting of public thoroughfares
 */

import type {
  EvidenceChainItem,
  RegulatoryRequirement,
  SpecificationRequirement,
  Standard,
  StandardRelationship,
} from './types';

// ─── Detection ────────────────────────────────────────────────────────────────

/** Marker embedded in the tender title when the LED sample button is pressed. */
export const LED_DEMO_TITLE_MARKER = 'MCD-2024-LT-09';

export function isLedDemoRaw(raw: any): boolean {
  const title: string = raw?.tender_title || '';
  return title.includes(LED_DEMO_TITLE_MARKER);
}

// ─── Standards ────────────────────────────────────────────────────────────────

export const LED_STANDARDS: Standard[] = [
  {
    id: 'led-std-16107',
    number: 'IS 16107:2023',
    title: 'LED Luminaires for Road and Street Lighting — Performance Requirements',
    category: 'Lighting & LED',
    edition: '2023',
    revision: '2023',
    status: 'current',
    bureau: 'BIS (29.140.40)',
    section: 'ETD 24',
    yearPublished: 2023,
    lastUpdatedDate: '2026-09-11',
    pages: 24,
    summary:
      'Specifies performance requirements for LED luminaires used in road and street lighting. Covers luminous efficacy (lm/W), correlated colour temperature (CCT), colour rendering index (CRI), lumen maintenance (L70/L80), power factor, total harmonic distortion (THD), and minimum IP66 enclosure protection.',
    keywords: ['LED', 'road luminaire', 'street luminaire', 'luminous efficacy', 'CCT', 'CRI', 'IP66', 'THD', 'lumen maintenance', 'L70'],
    referencedBy: ['IS 10322 : Part 5 : Sec 3'],
    references: ['IS 10322 : Part 5 : Sec 3', 'IS 1944 : Part 1 and 2', 'IS 16106'],
    isCertified: true,
    certificationBody: 'Bureau of Indian Standards (BIS)',
    regulatory: true,
    regulatoryNote:
      'Mandatory BIS Compulsory Registration Scheme (CRS) under QCO 2020. Bidders must hold valid CRS registration for LED luminaire and electronic driver before supply.',
    technicalCoverage:
      'Luminous efficacy ≥135 lm/W; CCT 4000K–5000K; CRI ≥70; L70 lumen maintenance ≥30 000 h; THD <10%; power factor ≥0.9; IP66 (minimum).',
    testingRequirements: 'Photometric test, lumen maintenance test, IP test (IS/IEC 60529), THD measurement, thermal test.',
    internationalEquivalents: ['IEC 62612', 'IEC TR 62778'],
    relationshipRole: 'primary',
    applicabilityScore: 97,
    whyApplies:
      'Specifies performance requirements for complete LED luminaires used for road and street lighting applications. Covers luminous efficacy, colour quality (CCT, CRI, Ra), IP rating, THD, and lumen maintenance — all directly referenced by this procurement.',
    whyAppliesReasons: [
      { category: 'Product match', description: 'LED luminaire for road and street lighting', matched: true },
      { category: 'Performance', description: 'Efficacy ≥135 lm/W, CCT 4000K–5000K, THD <10%', matched: true },
      { category: 'Weatherproofing', description: 'IP66 minimum for outdoor luminaires', matched: true },
      { category: 'Certification', description: 'CRS registration mandatory under QCO 2020', matched: true },
    ],
    evidenceAvailable: true,
    reviewConfidence: 'high-confidence',
    humanDecision: 'accepted',
    bisSourceUrl: 'https://www.bis.gov.in',
    retrievedAt: '2026-09-11',
    fieldAvailability: {
      scope: 'verified',
      normative_references: 'verified',
      certification: 'verified',
      test_methods: 'verified',
    },
  },
  {
    id: 'led-std-10322p5s3',
    number: 'IS 10322 : Part 5 : Sec 3',
    title: 'Luminaires — Part 5: Particular Requirements — Section 3: Luminaires for Road and Street Lighting',
    category: 'Lighting & LED',
    edition: '2013',
    revision: '2013',
    status: 'current',
    bureau: 'BIS (29.140.40)',
    section: 'ETD 24',
    yearPublished: 2013,
    lastUpdatedDate: '2026-09-11',
    pages: 18,
    summary:
      'Specifies particular safety, construction, and performance requirements for luminaires designed for road and street lighting, including LED types. Covers ingress protection (IP66), surge immunity, mechanical robustness, and thermal management.',
    keywords: ['luminaires', 'road lighting', 'street lighting', 'LED', 'IP66', 'surge immunity', 'outdoor lighting'],
    referencedBy: [],
    references: ['IS 10322 : Part 1'],
    isCertified: true,
    certificationBody: 'Bureau of Indian Standards (BIS)',
    regulatory: false,
    regulatoryNote: null,
    technicalCoverage:
      'IP66 ingress protection for both optics and controlgear compartment; ≥10 kV surge immunity (IEC 61000-4-5 Level 4); thermal endurance; mechanical impact resistance IK08.',
    testingRequirements: 'IP test per IS/IEC 60529, surge immunity per IEC 61000-4-5, thermal endurance test.',
    internationalEquivalents: ['IEC 60598-2-3'],
    relationshipRole: 'normative',
    applicabilityScore: 91,
    whyApplies:
      'Directly governs the construction, safety, and ingress protection requirements for road and street luminaires. Mandates IP66 for both optic and controlgear compartments and surge immunity \u226510 kV \u2014 matching the tender explicit requirements.',
    whyAppliesReasons: [
      { category: 'Product match', description: 'Luminaires for road and street lighting', matched: true },
      { category: 'IP protection', description: 'IP66 for optics and controlgear', matched: true },
      { category: 'Surge immunity', description: '≥10 kV driver surge protection', matched: true },
    ],
    evidenceAvailable: true,
    reviewConfidence: 'high-confidence',
    humanDecision: 'accepted',
    bisSourceUrl: 'https://www.bis.gov.in',
    retrievedAt: '2026-09-11',
    fieldAvailability: { scope: 'verified', certification: 'verified' },
  },
  {
    id: 'led-std-10322p1',
    number: 'IS 10322 : Part 1',
    title: 'Luminaires — Part 1: General Requirements and Tests',
    category: 'Lighting & LED',
    edition: '2013',
    revision: '2013',
    status: 'current',
    bureau: 'BIS (29.140.40)',
    section: 'ETD 24',
    yearPublished: 2013,
    lastUpdatedDate: '2026-09-11',
    pages: 32,
    summary:
      'Specifies general safety requirements and test methods applicable to all luminaire types including LED. Covers electrical insulation, thermal endurance (including thermal cut-out requirements), mechanical construction, and basic safety.',
    keywords: ['luminaires', 'general requirements', 'safety', 'testing', 'LED', 'thermal cutout'],
    referencedBy: ['IS 10322 : Part 5 : Sec 3'],
    references: [],
    isCertified: true,
    certificationBody: 'Bureau of Indian Standards (BIS)',
    regulatory: false,
    regulatoryNote: null,
    technicalCoverage:
      'Operating voltage 230V AC ±10%; thermal auto-cutoff (TCO) requirements for driver protection; electrical insulation class; 440V overvoltage endurance; mechanical stability.',
    testingRequirements: 'Thermal endurance test, electrical insulation test, voltage endurance test.',
    internationalEquivalents: ['IEC 60598-1'],
    relationshipRole: 'normative',
    applicabilityScore: 85,
    whyApplies:
      'Foundation safety standard for all luminaires. Covers operating voltage tolerance (230V AC ±10%), thermal auto-cutoff requirements for the driver, and general electrical safety — all referenced in IS 10322 Part 5 Sec 3.',
    whyAppliesReasons: [
      { category: 'Safety', description: 'General luminaire safety and test methods', matched: true },
      { category: 'Voltage', description: '230V AC ±10% operating range', matched: true },
      { category: 'Thermal', description: 'Thermal auto-cutoff (TCO) for driver protection', matched: true },
    ],
    evidenceAvailable: true,
    reviewConfidence: 'high-confidence',
    humanDecision: 'accepted',
    bisSourceUrl: 'https://www.bis.gov.in',
    retrievedAt: '2026-09-11',
    fieldAvailability: { scope: 'verified', certification: 'verified' },
  },
  {
    id: 'led-std-16106',
    number: 'IS 16106',
    title: 'Method of Electrical and Photometric Measurements of Solid State Lighting (LED) Products',
    category: 'Lighting & LED',
    edition: '2013',
    revision: '2013',
    status: 'current',
    bureau: 'BIS (29.140.40)',
    section: 'ETD 24',
    yearPublished: 2013,
    lastUpdatedDate: '2026-09-11',
    pages: 16,
    summary:
      'Defines electrical and photometric measurement methods for LED lighting products. Prescribes the test procedures for luminous flux, luminous efficacy (lm/W), colour temperature (CCT), CRI, and power measurements used in type-test reports.',
    keywords: ['LED', 'photometric', 'measurement', 'lm/W', 'CCT', 'CRI', 'type test'],
    referencedBy: ['IS 16107'],
    references: [],
    isCertified: false,
    certificationBody: null,
    regulatory: false,
    regulatoryNote: null,
    technicalCoverage:
      'Photometric measurement setup (goniophotometer or integrating sphere), lumen output measurement, luminous efficacy calculation (lm/W), CCT and CRI measurement, power factor and THD measurement.',
    testingRequirements: 'NABL-accredited laboratory required for type-test reports accepted by BIS.',
    internationalEquivalents: ['IEC 62612', 'IEC TR 62778'],
    relationshipRole: 'related',
    applicabilityScore: 80,
    whyApplies:
      'Defines the measurement methods by which luminous efficacy (≥135 lm/W), CCT, and CRI claims in the tender are verified. NABL-accredited labs performing IP66 and photometry type tests must follow this standard.',
    whyAppliesReasons: [
      { category: 'Testing', description: 'Photometric measurement methods for LED products', matched: true },
      { category: 'Evidence', description: 'Basis for NABL test reports submitted at bid', matched: true },
    ],
    evidenceAvailable: true,
    reviewConfidence: 'needs-review',
    humanDecision: 'reviewed',
    bisSourceUrl: 'https://www.bis.gov.in',
    retrievedAt: '2026-09-11',
    fieldAvailability: { scope: 'verified' },
  },
  {
    id: 'led-std-1944p1',
    number: 'IS 1944 : Part 1 and 2',
    title: 'Code of Practice for Lighting of Public Thoroughfares — General Principles and Lighting for Main and Secondary Traffic Routes',
    category: 'Lighting & LED',
    edition: '1981',
    revision: '1981',
    status: 'current',
    bureau: 'BIS (29.140.40)',
    section: 'ETD 24',
    yearPublished: 1981,
    lastUpdatedDate: '2026-09-11',
    pages: 28,
    summary:
      'Provides general principles and illuminance/luminance requirements for public road lighting. Covers arterial roads and highways, lux levels, uniformity ratios, and application guidance for main traffic routes.',
    keywords: ['public thoroughfare', 'road lighting', 'arterial roads', 'luminance', 'illuminance', 'uniformity'],
    referencedBy: ['IS 16107'],
    references: [],
    isCertified: false,
    certificationBody: null,
    regulatory: false,
    regulatoryNote: null,
    technicalCoverage:
      'Average road luminance and illuminance requirements for arterial roads; uniformity ratio; glare limitation; application classes for urban highways.',
    testingRequirements: '',
    internationalEquivalents: ['CIE 115'],
    relationshipRole: 'related',
    applicabilityScore: 76,
    whyApplies:
      'Governs the application and design of lighting for arterial roads and highways — the exact deployment scenario stated in the tender. Sets the illuminance and uniformity requirements that the specified luminaires must achieve in situ.',
    whyAppliesReasons: [
      { category: 'Application', description: 'Arterial roads and public highways', matched: true },
      { category: 'Design', description: 'Illuminance and uniformity requirements for roads', matched: true },
    ],
    evidenceAvailable: true,
    reviewConfidence: 'needs-review',
    humanDecision: 'reviewed',
    bisSourceUrl: 'https://www.bis.gov.in',
    retrievedAt: '2026-09-11',
    fieldAvailability: { scope: 'verified' },
  },
];

// ─── Specification Requirements (11) ──────────────────────────────────────────
// 9 covered, 2 review → 82% coverage

export const LED_SPEC_REQUIREMENTS: SpecificationRequirement[] = [
  {
    id: 'led-req-01',
    analysisId: '',
    requirement: 'Intended Application — Municipal LED Street Lighting for Urban Arterial Roads and Highways',
    tenderEvidence:
      'Municipal tender for LED street lighting luminaires to be deployed on urban arterial roads and highways.',
    tenderSection: 'Application scope',
    applicableStandard: 'IS 1944 : Part 1 and 2',
    standardId: 'led-std-1944p1',
    clause: 'Part 1 Cl. 4',
    status: 'covered',
    whyMatters:
      'IS 1944 Part 1 & 2 sets the illuminance and luminance requirements for arterial roads and highways. Luminaire selection must meet these lux levels in service; failure to cite this standard leaves uniformity requirements unspecified.',
    supportingEvidence: 'IS 1944 Part 1 Cl. 4 defines road class M1/M2 luminance requirements for main traffic routes.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-02',
    analysisId: '',
    requirement: 'Rated Wattage: 90W–120W LED Luminaire',
    tenderEvidence: '90W to 120W commercial LED street lighting luminaires.',
    tenderSection: 'Technical parameters',
    applicableStandard: 'IS 16107:2023',
    standardId: 'led-std-16107',
    clause: 'Cl. 5.1',
    status: 'covered',
    whyMatters:
      'IS 16107 Cl. 5.1 requires rated wattage to be declared and tested at nominal voltage. The range 90W–120W must be confirmed by type-test at each wattage point; range specifications must be supported by individual type-test data.',
    supportingEvidence: 'IS 16107 Cl. 5.1: rated wattage declared at nominal input voltage ±10%.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-03',
    analysisId: '',
    requirement: 'Operating Voltage: 230V AC ±10%, 50 Hz',
    tenderEvidence: 'Luminaires operating at 230V AC ±10%, 50 Hz supply.',
    tenderSection: 'Technical parameters',
    applicableStandard: 'IS 10322 : Part 1',
    standardId: 'led-std-10322p1',
    clause: 'Cl. 4.22',
    status: 'covered',
    whyMatters:
      'IS 10322 Part 1 Cl. 4.22 specifies the supply voltage tolerance range. Luminaires must perform within specification across the full ±10% range; this requirement is not met by specifying nominal voltage only.',
    supportingEvidence: 'IS 10322 Part 1 Cl. 4.22: equipment rated for supply at 230V AC ±10% (207V–253V).',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-04',
    analysisId: '',
    requirement: 'Minimum System Efficacy: ≥135 lm/W',
    tenderEvidence: 'High efficacy — minimum 135 lm/W.',
    tenderSection: 'Performance requirements',
    applicableStandard: 'IS 16107:2023',
    standardId: 'led-std-16107',
    clause: 'Cl. 5.2',
    status: 'covered',
    whyMatters:
      'IS 16107 Cl. 5.2 specifies how system luminous efficacy (complete luminaire lm/W) is measured and declared. The tender threshold of 135 lm/W must be validated by NABL type-test using the method in IS 16106.',
    supportingEvidence: 'IS 16107 Cl. 5.2: minimum luminous efficacy of complete LED luminaire at rated wattage.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-05',
    analysisId: '',
    requirement: 'IP66 Ingress Protection (Optics and Controlgear Compartments)',
    tenderEvidence: 'IP66 outdoor weatherproofing.',
    tenderSection: 'Performance requirements',
    applicableStandard: 'IS 10322 : Part 5 : Sec 3',
    standardId: 'led-std-10322p5s3',
    clause: 'Cl. 9',
    status: 'covered',
    whyMatters:
      'IS 10322 Part 5 Sec 3 Cl. 9 mandates IP66 for both the optical and controlgear compartments of road luminaires. The tender should specify both compartments; stating only "IP66" without the compartment distinction may allow non-compliant bids.',
    supportingEvidence:
      'IS 10322 Part 5 Sec 3 Cl. 9: both optical compartment and controlgear must independently achieve IP66 per IS/IEC 60529.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-06',
    analysisId: '',
    requirement: 'Correlated Colour Temperature (CCT): 4000K–5000K (Cool White / Neutral White)',
    tenderEvidence: 'CCT between 4000K and 5000K.',
    tenderSection: 'Performance requirements',
    applicableStandard: 'IS 16107:2023',
    standardId: 'led-std-16107',
    clause: 'Cl. 5.3',
    status: 'covered',
    whyMatters:
      'IS 16107 Cl. 5.3 specifies allowable CCT bins and tolerances. The tender CCT range (4000K–5000K) must be confirmed against the standard\'s MacAdam ellipse tolerance to prevent colour inconsistency across batches.',
    supportingEvidence: 'IS 16107 Cl. 5.3: CCT declared within 3-step MacAdam ellipse tolerance.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-07',
    analysisId: '',
    requirement: 'Total Harmonic Distortion (THD): <10% at Full Load',
    tenderEvidence: 'THD below 10%.',
    tenderSection: 'Performance requirements',
    applicableStandard: 'IS 16107:2023',
    standardId: 'led-std-16107',
    clause: 'Cl. 5.6',
    status: 'covered',
    whyMatters:
      'IS 16107 Cl. 5.6 limits THD to ≤10% at rated power to prevent harmonic distortion on the municipal grid supply. The tender correctly aligns with this limit; the measurement method per IS 16106 must be cited for test evidence.',
    supportingEvidence: 'IS 16107 Cl. 5.6: THD ≤10% of fundamental at rated voltage and full load.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-08',
    analysisId: '',
    requirement: 'Driver Surge Immunity: ≥10 kV (IEC 61000-4-5 Level 4)',
    tenderEvidence: '≥10 kV driver surge immunity.',
    tenderSection: 'Performance requirements',
    applicableStandard: 'IS 10322 : Part 5 : Sec 3',
    standardId: 'led-std-10322p5s3',
    clause: 'Cl. 12',
    status: 'covered',
    whyMatters:
      'IS 10322 Part 5 Sec 3 Cl. 12 specifies surge withstand immunity for road luminaire drivers. The ≥10 kV requirement corresponds to IEC 61000-4-5 Level 4; this must be validated by type-test certificate from an NABL-accredited EMC laboratory.',
    supportingEvidence:
      'IS 10322 Part 5 Sec 3 Cl. 12: surge immunity tested per IEC 61000-4-5; Level 4 (10 kV / 5 kA) for outdoor road luminaires.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-09',
    analysisId: '',
    requirement: 'Thermal Auto-Cutoff / Thermal Overload Protection for Driver',
    tenderEvidence: 'Thermal auto-cutoff protection for the LED driver.',
    tenderSection: 'Technical parameters',
    applicableStandard: 'IS 10322 : Part 1',
    standardId: 'led-std-10322p1',
    clause: 'Cl. 12.4',
    status: 'covered',
    whyMatters:
      'IS 10322 Part 1 Cl. 12.4 specifies thermal cut-out (TCO) requirements for luminaire drivers. The TCO must be a self-resetting or manual-reset device rated to interrupt the driver circuit before thermal damage; the reset method must be declared.',
    supportingEvidence:
      'IS 10322 Part 1 Cl. 12.4: thermal cut-out requirements — driver must have TCO that disconnects at the rated temperature limit.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-req-10',
    analysisId: '',
    requirement: 'NABL-Accredited Laboratory Test Evidence for IP66 and Photometric Performance',
    tenderEvidence: 'Bidders must submit NABL test reports for IP66.',
    tenderSection: 'Bidder submission requirements',
    applicableStandard: 'IS 16106',
    standardId: 'led-std-16106',
    clause: 'Test method',
    status: 'review',
    whyMatters:
      'The tender requires NABL test reports for IP66 verification. The test must follow IS/IEC 60529 for IP testing and IS 16106 for photometric measurements. The tender should explicitly state that photometry reports (efficacy, CCT, CRI) must also be NABL-accredited — currently only IP66 is specified.',
    supportingEvidence:
      'IS 16106 defines the photometric measurement procedure; NABL accreditation per ISO/IEC 17025 is required for test reports accepted in BIS certification.',
    suggestedAction:
      'Amend bid clause to require NABL-accredited test reports for both IP66 (IS/IEC 60529) AND photometric performance (IS 16106), not just IP66 alone.',
    reviewConfidence: 'needs-review',
  },
  {
    id: 'led-req-11',
    analysisId: '',
    requirement: 'BIS Compulsory Registration Scheme (CRS) — Mandatory Certification Evidence',
    tenderEvidence: 'Proof of BIS CRS compulsory registration.',
    tenderSection: 'Bidder submission requirements',
    applicableStandard: 'IS 16107:2023',
    standardId: 'led-std-16107',
    clause: 'QCO 2020',
    status: 'review',
    whyMatters:
      'BIS CRS registration under QCO 2020 is mandatory for LED luminaires and drivers before supply. The tender correctly requires CRS proof; however, it should clarify whether the CRS registration must cover both the LED module and the electronic driver separately (two distinct registrations may be required).',
    supportingEvidence:
      'QCO 2020 (LED Road and Street Luminaires) mandates BIS CRS registration. Bidders must submit valid CRS certificate numbers on letterhead; certificates must be current at time of supply.',
    suggestedAction:
      'Clarify that CRS registration is required separately for (a) the complete LED luminaire (IS 16107) and (b) the electronic driver/controlgear. State that CRS certificates must be valid at date of supply, not just at bid submission.',
    reviewConfidence: 'needs-review',
  },
];

// ─── Standard Relationships ────────────────────────────────────────────────────

export const LED_RELATIONSHIPS: StandardRelationship[] = [
  {
    id: 'led-rel-01',
    analysisId: '',
    fromStandardId: 'led-std-16107',
    toStandardId: 'led-std-10322p5s3',
    type: 'references',
    role: 'normative',
    label: 'IS 16107:2023 → IS 10322 : Part 5 : Sec 3',
    clause: 'Normative reference',
    description:
      'IS 16107 (LED luminaire performance) cites IS 10322 Part 5 Sec 3 as a normative reference for construction and safety requirements of road luminaires, including IP66 and surge immunity.',
    whyMatters:
      'Performance compliance under IS 16107 requires the luminaire to also satisfy the construction and safety clauses of IS 10322 Part 5 Sec 3. A supplier meeting only IS 16107 without IS 10322 Part 5 Sec 3 compliance is non-conformant.',
    evidenceSnippet: 'IS 16107:2023 Clause 2: "The following standards, the latest editions of which shall apply, are necessary adjuncts to this standard: IS 10322 (Part 5/Sec 3)."',
    evidenceSource: 'IS 16107:2023 Normative references, Cl. 2',
  },
  {
    id: 'led-rel-02',
    analysisId: '',
    fromStandardId: 'led-std-10322p5s3',
    toStandardId: 'led-std-10322p1',
    type: 'references',
    role: 'normative',
    label: 'IS 10322 P5S3 → IS 10322 : Part 1',
    clause: 'Normative reference',
    description:
      'IS 10322 Part 5 Sec 3 is a particular requirements standard that supplements — and normatively references — IS 10322 Part 1 (general requirements and tests) for all clauses not specifically overridden.',
    whyMatters:
      'Conformity with IS 10322 Part 5 Sec 3 implicitly requires full conformity with IS 10322 Part 1. The tender\'s IP66 and surge immunity requirements cannot be evaluated without Part 1 general safety tests.',
    evidenceSnippet: 'IS 10322 Part 5 Sec 3 Cl. 1.1: "This section supplements Part 1 of IS 10322; where no clause is provided, Part 1 applies."',
    evidenceSource: 'IS 10322 : Part 5 : Sec 3, Cl. 1.1',
  },
  {
    id: 'led-rel-03',
    analysisId: '',
    fromStandardId: 'led-std-16107',
    toStandardId: 'led-std-16106',
    type: 'references',
    role: 'related',
    label: 'IS 16107:2023 → IS 16106',
    clause: 'Test method reference',
    description:
      'IS 16107 references IS 16106 (Method of Electrical and Photometric Measurements of LED Products) as the measurement standard for verifying luminous efficacy, CCT, CRI, and THD claims.',
    whyMatters:
      'Efficacy and CCT test reports submitted under IS 16107 must use IS 16106 methodology to be accepted. NABL-accredited labs performing photometry for this tender must follow IS 16106.',
    evidenceSnippet: 'IS 16107 Cl. 5: "Measurements shall be carried out in accordance with IS 16106."',
    evidenceSource: 'IS 16107:2023, Cl. 5 (Measurement method)',
  },
  {
    id: 'led-rel-04',
    analysisId: '',
    fromStandardId: 'led-std-16107',
    toStandardId: 'led-std-1944p1',
    type: 'references',
    role: 'related',
    label: 'IS 16107:2023 → IS 1944 : Part 1 and 2',
    clause: 'Related reference',
    description:
      'IS 16107 references IS 1944 Part 1 & 2 for road lighting design requirements. The luminaire performance requirements in IS 16107 are intended to enable compliance with IS 1944 luminance and illuminance criteria.',
    whyMatters:
      'Luminaires meeting IS 16107 performance requirements are specified to achieve the road illuminance levels required by IS 1944 for arterial roads. The two standards together form the complete regulatory framework for this procurement.',
    evidenceSnippet: 'IS 16107 Scope: "…luminaires intended to meet the illumination requirements of IS 1944 for public road lighting."',
    evidenceSource: 'IS 16107:2023 Scope and IS 1944 Part 1 Cl. 4',
  },
];

// ─── Regulatory / Certification ───────────────────────────────────────────────

export const LED_REGULATORY: RegulatoryRequirement[] = [
  {
    id: 'led-reg-01',
    analysisId: '',
    requirement: 'BIS Compulsory Registration Scheme (CRS) — LED Road and Street Luminaires under QCO 2020',
    type: 'certification',
    status: 'applicable',
    relatedStandard: 'IS 16107:2023',
    relatedStandardId: 'led-std-16107',
    issuingAuthority: 'Bureau of Indian Standards (BIS)',
    sourceDocument: 'Quality Control Order — LED Road and Street Luminaires (QCO 2020)',
    orderNumber: 'QCO 2020 / IS 16107',
    effectiveDate: '2020-01-01',
    validityInfo: 'CRS certificate must be valid at date of supply (not just bid submission). Each product model requires separate registration.',
    whyAppliesText:
      'LED road and street luminaires are notified under a Quality Control Order requiring mandatory BIS Compulsory Registration Scheme (CRS) certification. Bidders must hold a valid CRS registration number for each luminaire model quoted. The tender explicitly states this requirement.',
    whyAppliesCriteria: [
      { text: 'Tender explicitly requires proof of BIS CRS compulsory registration', matched: true },
      { text: 'LED luminaires are notified under QCO 2020 for CRS mandatory certification', matched: true },
      { text: 'Registration must cover each wattage variant (90W and 120W separately)', matched: true },
      { text: 'CRS certificate must be in the name of the bidder (not third-party)', matched: true },
    ],
    evidenceAvailable: true,
    evidenceSnippet:
      '"Bidders must submit NABL test reports for IP66 and proof of BIS CRS compulsory registration." — Tender description.',
    evidenceLocation: 'Tender specification — Submission requirements',
    evidenceId: 'led-ev-11',
    reviewConfidence: 'high-confidence',
    decision: 'accepted',
  },
  {
    id: 'led-reg-02',
    analysisId: '',
    requirement: 'NABL-Accredited Laboratory Accreditation — IP66 and Photometric Type Tests',
    type: 'testing-accreditation',
    status: 'applicable',
    relatedStandard: 'IS 16106 / IS/IEC 60529',
    relatedStandardId: 'led-std-16106',
    issuingAuthority: 'National Accreditation Board for Testing and Calibration Laboratories (NABL)',
    sourceDocument: 'Tender technical specification — bidder submission requirements',
    orderNumber: 'NABL / ISO/IEC 17025',
    effectiveDate: 'Active (per tender submission deadline)',
    validityInfo: 'Test reports must not be older than 24 months from the bid submission deadline.',
    whyAppliesText:
      'The tender explicitly requires NABL-accredited test reports for IP66 verification. Additionally, photometric type-test reports (luminous efficacy, CCT, CRI, THD) submitted for CRS certification must originate from NABL-accredited laboratories following IS 16106 methodology. Both are requirements from the bidder.',
    whyAppliesCriteria: [
      { text: 'Tender requires NABL test reports for IP66 (IS/IEC 60529)', matched: true },
      { text: 'Photometric reports (lm/W, CCT, THD) must follow IS 16106 at NABL-accredited lab', matched: true },
      { text: 'Test report validity: not older than 24 months at bid submission', matched: true },
      { text: 'Laboratory must hold current NABL accreditation scope covering photometry and IP testing', matched: true },
    ],
    evidenceAvailable: true,
    evidenceSnippet:
      '"Bidders must submit NABL test reports for IP66…" and photometric efficacy claims per IS 16107 require IS 16106 methodology.',
    evidenceLocation: 'Tender specification — Submission requirements and IS 16107 Cl. 5',
    evidenceId: 'led-ev-10',
    reviewConfidence: 'high-confidence',
    decision: 'accepted',
  },
];

// ─── Evidence Chain ────────────────────────────────────────────────────────────

export const LED_EVIDENCE: EvidenceChainItem[] = [
  {
    id: 'led-ev-01', analysisId: '',
    requirement: 'Intended application — municipal LED street lighting, arterial roads',
    standard: 'IS 1944 : Part 1 and 2', standardId: 'led-std-1944p1', clause: 'Part 1 Cl. 4',
    evidence: 'Provides illuminance/luminance requirements for main traffic routes and arterial roads. Road class M1 applies.',
    sourceDoc: 'IS 1944 : Part 1 and 2 (BIS)', sourceLocation: 'Cl. 4 — Main traffic routes',
    status: 'supported', conclusion: 'Application scope matches IS 1944 Part 1 road class M1 (arterial roads).',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-02', analysisId: '',
    requirement: 'Rated wattage: 90W–120W LED luminaire',
    standard: 'IS 16107:2023', standardId: 'led-std-16107', clause: 'Cl. 5.1',
    evidence: 'Rated wattage must be declared and type-tested at nominal voltage ±10% for each wattage point in the range.',
    sourceDoc: 'IS 16107:2023 (BIS)', sourceLocation: 'Cl. 5.1 — Rated wattage',
    status: 'supported', conclusion: 'Wattage range 90W–120W is within IS 16107 scope; individual type tests required per wattage.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-03', analysisId: '',
    requirement: 'Operating voltage: 230V AC ±10%, 50 Hz',
    standard: 'IS 10322 : Part 1', standardId: 'led-std-10322p1', clause: 'Cl. 4.22',
    evidence: 'Luminaires rated for 230V AC supply must perform within specification over 207V–253V (±10%).',
    sourceDoc: 'IS 10322 : Part 1 (BIS)', sourceLocation: 'Cl. 4.22 — Supply voltage tolerance',
    status: 'supported', conclusion: '230V AC ±10% is standard operating range specified in IS 10322 Part 1.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-04', analysisId: '',
    requirement: 'System efficacy: ≥135 lm/W',
    standard: 'IS 16107:2023', standardId: 'led-std-16107', clause: 'Cl. 5.2',
    evidence: 'Luminous efficacy of complete luminaire (lm/W) measured at rated wattage using IS 16106 method.',
    sourceDoc: 'IS 16107:2023 (BIS)', sourceLocation: 'Cl. 5.2 — Luminous efficacy',
    status: 'supported', conclusion: '135 lm/W threshold aligns with IS 16107 minimum efficacy for urban road lighting.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-05', analysisId: '',
    requirement: 'IP66 ingress protection (optics and controlgear)',
    standard: 'IS 10322 : Part 5 : Sec 3', standardId: 'led-std-10322p5s3', clause: 'Cl. 9',
    evidence: 'Both optical and controlgear compartments must independently achieve IP66 per IS/IEC 60529.',
    sourceDoc: 'IS 10322 : Part 5 : Sec 3 (BIS)', sourceLocation: 'Cl. 9 — Degree of protection (IP)',
    status: 'supported', conclusion: 'IP66 requirement is directly mandated by IS 10322 Part 5 Sec 3 Cl. 9 for road luminaires.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-06', analysisId: '',
    requirement: 'CCT: 4000K–5000K',
    standard: 'IS 16107:2023', standardId: 'led-std-16107', clause: 'Cl. 5.3',
    evidence: 'CCT declared within 3-step MacAdam ellipse tolerance; 4000K–5000K range falls within neutral/cool white bins.',
    sourceDoc: 'IS 16107:2023 (BIS)', sourceLocation: 'Cl. 5.3 — Colour temperature',
    status: 'supported', conclusion: 'CCT 4000K–5000K maps to IS 16107 Cl. 5.3 neutral/cool white requirement.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-07', analysisId: '',
    requirement: 'THD: <10% under full load',
    standard: 'IS 16107:2023', standardId: 'led-std-16107', clause: 'Cl. 5.6',
    evidence: 'THD ≤10% of fundamental current at rated voltage and full load. Measurement per IS 16106.',
    sourceDoc: 'IS 16107:2023 (BIS)', sourceLocation: 'Cl. 5.6 — Total harmonic distortion',
    status: 'supported', conclusion: 'THD <10% is directly compliant with IS 16107 Cl. 5.6 limit.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-08', analysisId: '',
    requirement: 'Driver surge immunity: ≥10 kV',
    standard: 'IS 10322 : Part 5 : Sec 3', standardId: 'led-std-10322p5s3', clause: 'Cl. 12',
    evidence: 'Surge withstand test per IEC 61000-4-5 Level 4 (10 kV / 5 kA combination wave). Road luminaires require Level 4.',
    sourceDoc: 'IS 10322 : Part 5 : Sec 3 (BIS)', sourceLocation: 'Cl. 12 — Surge immunity',
    status: 'supported', conclusion: '≥10 kV surge immunity requirement matches IS 10322 Part 5 Sec 3 Cl. 12 Level 4 mandate.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-09', analysisId: '',
    requirement: 'Thermal auto-cutoff for driver',
    standard: 'IS 10322 : Part 1', standardId: 'led-std-10322p1', clause: 'Cl. 12.4',
    evidence: 'Thermal cut-out (TCO) must interrupt driver circuit before thermal damage; reset method must be declared.',
    sourceDoc: 'IS 10322 : Part 1 (BIS)', sourceLocation: 'Cl. 12.4 — Thermal cut-out',
    status: 'supported', conclusion: 'Thermal auto-cutoff requirement maps directly to IS 10322 Part 1 Cl. 12.4 TCO mandate.',
    reviewConfidence: 'high-confidence',
  },
  {
    id: 'led-ev-10', analysisId: '',
    requirement: 'NABL test evidence for IP66 and photometric performance',
    standard: 'IS 16106', standardId: 'led-std-16106', clause: 'Test method',
    evidence: 'IS 16106 defines measurement method; NABL accreditation per ISO/IEC 17025 required for BIS-accepted reports.',
    sourceDoc: 'IS 16106 (BIS) / NABL accreditation framework', sourceLocation: 'IS 16106 Cl. 1',
    status: 'needs-review', conclusion: 'Tender requires NABL reports for IP66 only; photometric NABL requirement should be made explicit.',
    reviewConfidence: 'needs-review',
  },
  {
    id: 'led-ev-11', analysisId: '',
    requirement: 'BIS CRS compulsory registration evidence',
    standard: 'IS 16107:2023', standardId: 'led-std-16107', clause: 'QCO 2020',
    evidence: 'LED road luminaires are notified under QCO 2020. Valid CRS certificate per model and wattage required before supply.',
    sourceDoc: 'Quality Control Order 2020 (LED Road and Street Luminaires)', sourceLocation: 'QCO 2020 — Schedule',
    status: 'needs-review', conclusion: 'CRS registration required; tender should clarify whether driver and module need separate CRS numbers.',
    reviewConfidence: 'needs-review',
  },
];

// ─── Specification improvement suggestions (for the AI panel) ──────────────────

export interface ImprovementSuggestion {
  id: string;
  area: string;
  whatToImprove: string;
  whyItMatters: string;
  suggestedWording: string;
}

export const LED_IMPROVEMENT_SUGGESTIONS: ImprovementSuggestion[] = [
  {
    id: 'imp-01',
    area: 'Efficacy measurement basis',
    whatToImprove: 'The efficacy requirement "≥135 lm/W" does not specify whether it applies to the LED module, the driver, or the complete luminaire system.',
    whyItMatters: 'Module-level efficacy is typically 15–20% higher than system efficacy. A bidder could quote LED module efficacy and still deliver a luminaire system below 135 lm/W, making evaluation ambiguous.',
    suggestedWording: 'The complete LED luminaire system luminous efficacy (including all driver losses) shall be ≥135 lm/W at rated wattage and nominal supply voltage, measured in accordance with IS 16106 at an NABL-accredited laboratory.',
  },
  {
    id: 'imp-02',
    area: 'IP66 — compartment clarity',
    whatToImprove: 'The tender states "IP66 outdoor weatherproofing" without specifying that both the optical compartment and the controlgear compartment must independently achieve IP66.',
    whyItMatters: 'IS 10322 Part 5 Sec 3 requires both compartments to be independently IP66 rated. A bid with IP66 optics but only IP54 controlgear could technically pass a loose specification, leading to driver failures in service.',
    suggestedWording: 'Both the optical compartment and the controlgear/driver compartment shall independently achieve a minimum ingress protection rating of IP66 as per IS/IEC 60529, verified by separate NABL-accredited test reports.',
  },
  {
    id: 'imp-03',
    area: 'CRS registration scope',
    whatToImprove: 'The BIS CRS requirement does not clarify whether registration is needed for the complete luminaire, the LED driver, or both, and whether each wattage point requires a separate certificate.',
    whyItMatters: 'QCO 2020 requires CRS registration for LED road luminaires. In practice, the luminaire and the electronic driver may require separate CRS registrations. Ambiguity can be exploited post-award or cause rejection at goods acceptance.',
    suggestedWording: 'Bidders shall submit valid BIS CRS registration certificates for (a) the complete LED luminaire under IS 16107, and (b) the electronic driver/controlgear, for each wattage variant quoted (90W and 120W separately). Certificates must be valid at the date of supply.',
  },
  {
    id: 'imp-04',
    area: 'Photometric NABL evidence scope',
    whatToImprove: 'The tender requires NABL test reports for IP66 only. It does not explicitly require NABL-accredited photometric reports for efficacy, CCT, and THD claims.',
    whyItMatters: 'Without explicit NABL accreditation for photometry, bidders can submit in-house test data for efficacy and CCT. This creates unfair advantage and unreliable performance guarantees in service.',
    suggestedWording: 'Bidders shall submit type-test reports from NABL-accredited laboratories for: (i) IP66 ingress protection per IS/IEC 60529, (ii) luminous efficacy and photometric performance per IS 16106, and (iii) surge immunity per IEC 61000-4-5. All reports must be not older than 24 months from the bid submission date.',
  },
  {
    id: 'imp-05',
    area: 'Surge immunity test standard reference',
    whatToImprove: 'The tender specifies "≥10 kV driver surge immunity" but does not reference the applicable test standard (IEC 61000-4-5) or the required level.',
    whyItMatters: 'Without citing the test standard, bidders may use non-standardised surge test procedures. Evaluation of competing test reports becomes inconsistent. IS 10322 Part 5 Sec 3 Cl. 12 requires Level 4 (10 kV/5 kA).',
    suggestedWording: 'The LED driver shall withstand a minimum surge immunity of 10 kV / 5 kA (common mode and differential mode) as per IEC 61000-4-5 Level 4, tested per IS 10322 (Part 5/Sec 3) Cl. 12. NABL-accredited test certificate is mandatory.',
  },
  {
    id: 'imp-06',
    area: 'Lumen maintenance / lifetime requirement',
    whatToImprove: 'The tender specifies efficacy at commissioning but does not include a lumen maintenance requirement (L70 or L80 hours), which is a standard IS 16107 performance parameter.',
    whyItMatters: 'A luminaire could meet 135 lm/W at commissioning but degrade rapidly. IS 16107 requires L70 lumen maintenance data (flux at 70% of initial value) to be declared; without it, lifetime cost calculations and re-lamping schedules cannot be evaluated.',
    suggestedWording: 'The luminaire shall demonstrate L70 lumen maintenance of not less than 50 000 hours at 25°C ambient, as declared by the manufacturer per IS 16107 Cl. 5.4 and supported by IES TM-21 / LM-80 extrapolation data from NABL-accredited laboratory test.',
  },
];
