# PROGRESS

## Durum
Aktif faz: 6 (test koşumu) — Q-V0-1 önbellekten yeniden oynatmayla kapandı, A0 devam ediyor ·
Faz 7 tamam · Faz 8: V1–V7 tamam, demo Streamlit Community Cloud'a (Q-F8-2) hazırlanıyor ·
Son güncelleme: 2026-09-22.

## Dondurulmuş değerler
**DONDURULDU 2026-09-20, test koşumundan önce.** Test koşumu başladıktan sonra biri değişirse
tüm test sonuçları geçersizdir ve baştan koşulur.
| ne | değer |
|---|---|
| model | `gemini-3.1-flash-lite` (Google AI Studio ücretsiz katman) |
| API | REST `v1beta` (`config.GEMINI_API_VERSION`) |
| PROMPT_VERSION | `v5` (hash `2843aa42…`, `prompts.PROMPT_HASHES`) |
| sinyal | z ≥ 4,25 (τ_z; mutlak τ = 0,70 yedek) |
| embedding modeli | `BAAI/bge-small-en-v1.5` |
| data seed | 42 |
| gözlenen RPD | **500, ölçüldü** (2026-09-20'de 490. istekten sonra günlük 429 geldi, `QuotaFailure` değeri 500; `quota_log.json` → `observed_rpd`) · RPM 15 |
| git SHA | dondurma commit'i `fc05ccc`; her sonuç satırı kendi `git_sha`'sını taşır (results.md metadata'sında da görünür) |
| koşum planı | 665 cevap (A0 ×3, A1–A5 ×1) |

## Harcama ve kota
Para: $0 (D25). Kota **proje + model başına**: Lite olmayan her Flash modeli RPD 20 / RPM 5,
Flash-Lite RPD 500 / RPM 15 (AI Studio, Ozan 2026-09-20; 3.7'de RPD 20 429'dan da ölçüldü).
`eval/results/quota_log.json` seçilen modeli izler (2026-09-20: 490 istek / 1.244.097 token —
aday koşumu + üç dev iterasyonu + test A0 r1'in ilk 23 cevabı; gün kotayla kapandı,
`observed_rpd` 500 olarak öğrenildi). Aday koşumlarının kendi log'ları
`eval/results/scratch/model_pick/` altında (3.5-flash-lite 125 istek, 3.8-flash 16 istek +
günlük 429).
**Süre tahmini (Ozan'ın 15 gün sınırı):** ölçülen 3,3 LLM çağrısı/cevap × 665 cevap = 2.172
çağrı ÷ 500 = **5 gün** (+ dev iterasyonları, her biri ~100 çağrı, günü doldurmuyor). Sınırın
altında, durmaya gerek yok.

## Tamamlananlar
- [Faz 0] Paket iskeleti, pyproject, sabit requirements, .gitignore/.env.example/.dockerignore,
  config.py + testleri (2ea7765)
- [Faz 0] Kapı script'leri: check_all.py (ruff, format, pytest+cov, yasaklı terim, sır taraması),
  check_forbidden_terms.py + testleri (72228cc)
- [Faz 0] GitHub Actions iş akışı (d339f89) · LF satır sonu zorunluluğu (162d42e)
- [Faz 0] Kabul: `pip install -e .` ✅ · `import metacompass` ✅ · check_all → 0 ✅ ·
  yasaklı terim geçici dosyada yakalanıyor / dosya yokken 0 ✅ (test_check_scripts) ·
  sır taraması `sk-` yakalıyor ✅ · git status temiz, data/ ve docs/plan/ takip dışı ✅
- [Faz 1] `data/schema.py`: 7 satır modeli, enum'lar, ID regex'leri (329c52e)
- [Faz 1] Vocab: org, tables (80 tablo, elle tasarlanmış 149 kenarlı lineage), metrics (40),
  report_subjects (44 konu, 15 nitelendirici, açıklama şablonları, gürültü varyantları),
  request_topics (60 küme), reserved_near_miss (ebb3913)
- [Faz 1] `data/generate.py`: aşama başına seed'li RNG, 38 ayrılan / 5 devir yapısı, rapor, tablo,
  metrik ve talep üretimi, CSV + `_meta.json` yazımı; üretim ~1,5 sn (0879663)
- [Faz 1] Testler: I01–I17 + N3–N7 + X gerçekçilik kontrolleri (56 test); 17 farklı seed'de yeşil (0402db8)
- [Faz 1] `data/store.py`: MetadataStore (tipli satırlar, pandas frame'leri, lookup'lar) + 28 test (1f3d07d)
- [Faz 1] `scripts/describe_data.py` → `docs/data_card.md` + güncellik testi (f1c9b58)
- [Faz 1] Öğrenme notu: `docs/learn/01_synthetic_data_design.md`
- [Faz 1] Kabul: I01–I17 yeşil ✅ · üretim < 30 sn, LLM/ağ yok ✅ (~1,5 sn) · data card üretildi,
  "synthetic" notu var ✅ · vocab'ta yasaklı terim yok ⚠️ (H5 dosyası yok, tarama atlandı)
- [Faz 1 kontrol noktası] Ozan'ın düzeltmeleri: ayrılmış sahip oranı (I18), kazara yakın-kopya
  isim/başlık kontrolü (I19), bölge varyantı anlamsal çakışması (I14 ek testi), kalıp tiki (I20).
  Önce testler yazıldı ve kırmızı görüldü (6 + 1 başarısız), sonra üretici düzeltildi.
  63 invariant testi 17 seed'in hepsinde yeşil. Önce/sonra (seed 42):
  | ölçüm | önce | sonra |
  |---|---|---|
  | ayrılmış sahipli aktif rapor | %40,0 | %21,3 (I07 tabanı, 50/235) |
  | ayrılmış sahipli tablo / metrik | %31,2 / %32,5 | %17,5 / %17,5 |
  | kazara yakın-kopya rapor çifti (J>0,6) | 43 | 0 |
  | yakın-kopya metrik çifti | 1 (Gross Margin % / Parts Gross Margin) | 0 (→ "Parts Margin %") |
  | kümeler arası benzer talep başlığı | 0 (ama 17 seed'in 7'sinde >0) | 0 (17/17 seed) |
  | en sık açılış: rapor açıklaması | "shows" %14,0 | %8,4 |
  | en sık açılış: talep başlığı | "deep" %15,0 | %8,3 |
  | en sık açılış: talep açıklaması | "please" %23,3 | %10,0 |

- [Faz 2] Tokenizer (fc85f1b, fc4397a) · BM25 (8ba3298) · embedder'lar + cache (27d8188) ·
  hibrit RRF + MatchSignal + korpus (ecca670) · lineage grafı + mini fixture (a83e864) ·
  retrieval set + bağımsız gold (7ba7eea) · benchmark koşucusu + results.md (3d58479, 1d37885) ·
  benchmark sonuçları + τ (7cdffa2)
- [Faz 2] Öğrenme notları: 02_bm25, 03_dense_and_rrf, 04_match_quality_threshold, 05_graph_traversal
- [Faz 2] Kabul: unit testler yeşil (HashEmbedder) ✅ · `pytest -m slow` gerçek embedder ile yeşil ✅
  (`check_all.py --slow`: 211 test) · `eval/results/retrieval_bench.json` gerçek sonuçlarla ✅ ·
  beklenti kontrolü yazılı ✅ (aşağıda) · τ seçildi, gerekçesi yazılı ✅ (config.py + not 04)
- [Faz 2] **Beklenti kontrolü** (git 1d37885, 60 sorgu, top-10):
  | | BM25 | dense | hibrit |
  |---|---|---|---|
  | E r@1 | 1.00 | 0.53 | 0.67 |
  | P r@1 / r@5 | 0.20 / 0.47 | 0.13 / 0.27 | 0.20 / 0.40 |
  | D r@1 | 0.73 | 0.67 | 0.67 |
  | MRR (E+P+D) | 0.72 | 0.54 | 0.61 |
  - E'de BM25 > dense ✅. Hibrit < BM25: fark tamamen rapor-ID sorgularında (hibrit 0/5; tablo
    adı ve metrik kısaltmasında hibrit 1.00). Hipotez: dense metinde ID yok (§5.2), dense listesi
    ID sorgusunda gürültü; RRF'te BM25'in 1. sırası iki listede orta sırada olan belgeye yeniliyor.
  - P'de dense > BM25 ❌. Hipotezler: (1) **şablon sızıntısı** — 15 P sorgusunun 9'u hedefin
    açıklaması/etiketleriyle ≥2 içerik kelimesi paylaşıyor (parafraz havuzunu yazarken vocab
    ölçü ifadelerine bakmışım; isimle örtüşme kontrolü ≤%30 geçiyor, açıklama kontrol edilmiyor)
    → BM25 şişik; (2) nitelendirici ifadesi ("per calendar month") MiniLM embedding'ine baskın,
    dense'i başka konuların "Monthly …" raporlarına çekiyor; (3) korpustaki tablolar dense'i
    çekiyor (ör. `stg_dms_vehicle_sales`). Konu düzeyinde doğru aileyi BM25 11/15, dense 6/15 buluyor.
  - D'de hibrit > ikisi ❌. Deprecated çiftlerde üç mod da %50 (retrieval durumu bilmiyor, isimler
    neredeyse aynı — bunu agent `status`/`replaced_by` ile çözmeli); yakın-kopyada BM25 7/7.
  - **Modlar P ve D'de birbirine yakın** (P r@1 0.13–0.20, D r@1 0.67–0.73). Veri veya şablon
    beklentiye uydurulmak için değiştirilmedi.
  - τ: P kosinüsleri (medyan 0.45, 0.33–0.57) ile N kosinüsleri (medyan 0.46, 0.39–0.61) üst üste.
    F1-maksimum τ = 0.65'te negatiflerin 15/15'i weak ama P'lerin de 15/15'i weak; strong olan
    pozitiflerin hepsi exact_match sayesinde.

- [Faz 2 düzeltmeleri — Ozan'ın 2026-09-18 kararları]
  - I07 gevşetme + I18 ≤ %18 (3053480): aktif raporların ayrılmış sahip oranı %21,3 → %13,6 (taban);
    departman eşleşmesi %84; 17 seed × 63 invariant yeşil.
  - Builder doğrulamaları + parafraz havuzu (001b915): P açıklama örtüşmesi ≤ %20 (işlev kelimeleri ve
    şablon kelimeleri hariç), hedef tekliği; havuz tüm üretici kelimelerinden arındırıldı. v1'de ortalama
    %23 örtüşme ve 15'te 6 sorgu sınır üstündeydi; v2'de 0.
  - Göreli sinyal + yeni metrikler (7665139): `MatchSignal.dense_z`, `topic_hit@5`, `pair_coverage@5`,
    iki sinyal taraması, ön kayıtlı model A/B kuralı.
  - Yeniden koşum (35edadd): v1 seti eski üreticiyle (7cdffa2) yeniden üretilen veride yeniden puanlandı
    (orijinal sayıları birebir tekrarladı); v2 seti MiniLM + bge-small. Kural bge-small'u seçti
    (hibrit MRR 0,580 vs 0,541). Sinyal z ≥ 4,25 (F1 0,749; kosinüs 0,704). Tam eşleşme dışında
    15 P'den 1'i strong, 15 N'den 0'ı. `results.md` eski ve yeni tabloları + iki paragrafı içeriyor.
  - **Spec güncellendi** (`docs/plan/13_METACOMPASS_MASTER.md`): §4.4.2, §4.7 (I07, I18–I20),
    §5.5, §5.7, §5.8, §9.2, Ek C.2. `CLAUDE.md`'ye yeni karar yetkisi bölümü eklendi.

- [Faz 3] `tools/schemas.py` + 12 sahiplik testi + `ownership.py` (75741c6)
- [Faz 3] search + records, lineage + past_work, impact (D24), registry + `AgentConfig`; testler
  `test_tools.py`, `test_registry.py`, `test_gold_impact.py`, `test_config.py` (+3). Her test önce
  kırmızı görüldü (stub ya da mutasyonla). Tool/registry/gold testleri 17 seed'de yeşil.
  Commit'ler: aşağıdaki "Faz 3 kapanış" satırı.
- [Faz 3] Öğrenme notu: `docs/learn/06_owner_resolution.md`
- [Faz 3] Kabul: 12 sahiplik testi ✅ · §7.9 minimumları 6 tool'da ✅ · registry şemaları
  jsonschema Draft 2020-12 meta-şemasına uygun ✅ · gerçek veride `_meta.chains` ✅ (test 12,
  17 seed) · mimari testleri ✅
- [Faz 3] **Q-F3-1 kapandı → D24** (Ozan, 2026-09-18). `impact_analysis` ölçeğe göre biçim
  değiştiriyor. `eval/run_impact_fanout.py` → `eval/results/impact_fanout.json` (seed 42):
  | | individual (≤ 20 kişi) | broadcast (> 20 kişi) |
  |---|---|---|
  | tablo | **47** | **33** |
  | staging / intermediate / mart | 15 / 13 / 19 | 15 / 12 / 6 |
  | bildirilecek kişi aralığı | 4–17 | 21–72 |
  Broadcast'a düşen mart'lar: dim_vehicle (25), dim_dealer (35), dim_region (22), dim_date (50),
  fct_vehicle_sales (41), fct_service_orders (21). En büyük çıktı 6.000 karakter (sınırda); 40
  tabloda `affected_*` listeleri kırpılıyor, notify ve rollup hiçbirinde kırpılmıyor. Bildirilecek
  kişisi olmayan tablo yok.
- [Faz 3 kapanış] Commit'ler: 75741c6 sahiplik · e112efc search+records · 5417dc4 lineage+past_work ·
  0bc98e5 impact · b3ad7ee registry · 525a99f fan-out script'i · ardından docs ve fan-out JSON'u.
  Her commit öncesi tam kapı geçti (297 test).
- **Spec güncellendi, Q-F3-1 kapandı** (2026-09-18): §7.1 (tool başına sınır), §7.7 (şema, mod
  kuralı, 6.000 sınırı), §7.9, §8.4 (broadcast satırı), §9.2 (L5 = 7 individual + 3 broadcast; MX
  yalnızca individual tablolar; dev L5 = 2 + 1), §9.4 (`impact_notify` gold'u), §9.8 (A5 notu),
  Ek C.4 (sabitler), §15 D24. `CLAUDE.md`'ye sabitler eklendi.

- [Faz 4] Mimari testi: framework yasağı genişletildi (autogen, semantic_kernel, haystack,
  smolagents, pydantic_ai, OpenAI Agents SDK, litellm, instructor) + sağlayıcı SDK'larını yalnızca
  `agent/llm.py` import edebilir (d7c9ad3)
- [Faz 4] `agent/llm.py`: LLMClient protokolü, FakeLLM, CachedLLM, `cost_usd` (0600417)
- [Faz 4] `agent/answer.py`: FinalAnswer, `parse_final`, `enforce_grounding` (01b797a)
- [Faz 4] `agent/prompts.py`: §8.4 prompt'u v1 + D24 broadcast satırı; A3/A4/A5 bölümleri (4336652)
- [Faz 4] `agent/loop.py`: sınırlı döngü, §8.6'nın 12 senaryosu + 2 ek test, FakeLLM ile (53cee3d)
- [Faz 4] Öğrenme notları: `07_tool_calling_loop`, `08_grounding_and_abstain`
- [Faz 4] Kabul: 12 döngü senaryosu ağsız yeşil ✅ · grounding testleri ✅ · framework yok ✅ ·
  **live smoke ❌ atlandı:** `.env` yok (H1–H3 boş). ProviderClient (görev 6) ve
  `test_live_smoke.py` (görev 7) H1 gelince yazılacak; sağlayıcının güncel resmi dokümanına
  bakılması gerekiyor (§8.1).

- [Faz 5] `eval/gold.py` tamamı: §9.4'ün 8 tipi, D24 broadcast kuralı (7301f05) · mini fixture'da elle
  hesaplanan değerler + gerçek veride çapraz kontrol: resolve_owner (370 varlık), lineage BFS (tüm
  düğümler × derinlik 1/2/3/6), impact_analysis (80 tablo) — **uyuşmazlık yok** (de305a5)
- [Faz 5] `eval/scoring.py` + tablo tabanlı testler (4cff9a4)
- [Faz 5] Şablonlar (kategori başına ≥ 4) + 60 talep kümesi için parafraz havuzu + `question_sets.py`
  builder + doğrulamalar (fe82370) · `dev_set.json` (30), `test_set.json` (100) (e2fde88)
- [Faz 5] `eval/configs.py` (A0–A5; test setinde 1.030 koşum) + `eval/run_eval.py` (bütçe koruması,
  `--llm fake`) (6f62278) · `eval/agent_report.py` + `report.py` ajan bölümleri (62873c6)
- [Faz 5] Kuru koşum (görev 11): `run_eval.py --set dev --llm fake` (gerçek bge-small embedder) →
  30 cevap; "hep abstain" sahte model L6'da 6/6, geneli 0,20 · `report.py --results-dir
  eval/results/scratch --set dev` tüm ajan bölümlerini doldurdu, "not run" kalmadı. Çıktılar
  scratch'te, commit edilmedi. Ablation tablosunda bir sütun kayması bu koşumda yakalandı ve
  testle düzeltildi.
- [Faz 5] `eval/review_sample.md` üretildi (her kategoriden 3 test sorusu, gold isimleriyle; commit edilmez)
- [Faz 5] Öğrenme notu: `docs/learn/09_eval_design.md`
- [Faz 5] Kabul: gold bağımsızlık (mimari testi) ✅ · çapraz kontrolde uyuşmazlık yok ✅ · setler §9.2
  dağılımıyla birebir ✅ · kuru koşum uçtan uca ✅ · `review_sample.md` ✅

- [D25, 2026-09-19] **Sıfır para, ücretsiz katman** (Ozan'ın kararı):
  - Ayarlar: `LLM_RPM_LIMIT`, `LLM_RPD_LIMIT`, `LLM_TPM_LIMIT` (+ `.env.example`)
  - `GeminiClient`, REST `generateContent` (5708d61)
  - Döngü: kota durumu `llm_error` değil; her LLM adımı girdi bileşimini kaydediyor (9e56277)
  - `QuotaGuardedLLM`: RPM/TPM throttle, RPD'de duruş, 429 ipucu / jitter'lı geri çekilme (40e43ca)
  - Runner devam ettirilebilir; para koruması kaldırıldı; plan 665 (e7d4c73)
  - Rapor: koşum planı ve limitler bölümü, plandan "not answered yet", A0 gürültüsüne göre ≈
    işareti (4a74f94)
  - Token bileşimi ölçümü (1e39300, 3c871cb); LF düzeltmesi (b0f3084); canlı smoke testi
    (583ecd5); README + CLAUDE.md (48b8862)
  - **Kaldırılan testler:** para korumasının testleri (`--confirm`, `--i-know-the-cost`, pilot
    maliyet tahmini, bütçe dolunca `incomplete` satırı, spend_log). Test zayıflatma değil; Ozan'ın
    kararıyla kaldırılan özelliğin testleriydi. Yerlerine devam ettirme, anında yazma ve kotada
    temiz duruş testleri geldi.
- [D25] **Token ölçümü** (`eval/measure_input.py` → `eval/results/input_composition.json`, yalnızca
  dev seti). Her dev sorusu, gold'undan türetilen en kısa tool yoluyla, gerçek döngü ve registry'den
  senaryolu modelle geçirildi. Karakterler token'a ~4 karakter/token ile çevrildi (tahmin; dev
  pilotu gerçek sayıyı verecek).
  | | değer |
  |---|---|
  | LLM turu / soru (en kısa yol) | 2,6 |
  | input / soru | ~22.400 karakter ≈ **~5.600 token** |
  | tool tanımları | **%60** (6 tool, 5.179 karakter, her turda yeniden gönderiliyor) |
  | sistem prompt'u | %23 (1.988 karakter) |
  | tool çıktıları | %14,5 |
  | soru + modelin kendi turları | %2,3 |
  Kategoriye göre ortalama girdi: L1 16,4k · L4 16,0k · L6 16,1k · L2 25,8k · L3 27,0k · L5 28,6k ·
  MX 30,9k karakter. Kota hesabı: en kısa yolda 665 cevap ≥ ~1.730 çağrı. Gerçek agent daha çok tur
  atar; ~4.000 çağrı tahminiyle uyumlu.
- [D25] **Tool çıktısı ve tanımı bildirimi** (kırpılmadı, karar Ozan'ın):
  1. Tool tanımlarındaki Pydantic `"title"` anahtarları 448 karakter (tanımların %9'u, ~110 token/tur).
     Bilgi taşımıyorlar. En büyük kaldıraç çıktılar değil, her turda giden tanımlar.
  2. `search_assets`: `signal` içindeki sayısal alanlar (`top_dense_cosine`, `dense_z`,
     `exact_match`) çıktının ~%6'sı; model yalnızca `match_quality`'yi kullanıyor. `query`
     (modelin kendi sorgusunun yankısı) %5,4.
  3. `find_similar_past_work`: `signal` %7,6 (aynı gerekçe).
  4. Her çıktıda `"truncated":false` ~%1; `trace_lineage`'da raporlar için `layer`, tablolar için
     `status` null (~%3,4).
  5. `impact_analysis`: `affected_reports` çıktının %54'ü (rapor başına ad, durum, kullanım, bildirilen
     kişi, çözüm durumu); `notify` ile kısmen örtüşüyor ama "hangi raporlar bozulur" sorusunun cevabı
     bu. Dokunulmamalı bence.
  6. `resolve_owner`: `path` %50. Açıklama için gerekli, dokunulmamalı.
  Not: 1–4 prompt/şema değişikliği sayılır. Uygulanırsa `PROMPT_VERSION` artar ve dev setinde
  ölçülür (iterasyon hakkından düşer).

- [Faz 5 kontrolü] **`.env` ve push kontrolü (2026-09-19):** `.env` git'te yok sayılıyor, hiçbir
  commit'te yok; anahtar biçimi doğru, hiçbir çıktıya yazdırılmadı. `LLM_MODEL=gemini-1.5-flash`
  bu anahtarın model listesinde yoktu (liste çağrısı, kota harcamaz), **`gemini-3.7-flash`** seçildi (Flash,
  Lite değil; D25'in "Flash, Lite değil" kuralı) ve `.env`'de yalnızca bu satır değişti. Limitler
  (RPM 15 / RPD 1.500 / TPM 1M) eski 1.5 Flash değerlerine benziyor; gerçek limit daha düşükse
  guard 429'daki `QuotaFailure`'dan öğrenip `quota_log.json`'a yazıyor. `docs/plan/forbidden_terms.txt`
  ile tarama: çalışma ağacı ve tüm commit geçmişi temiz (terimler burada yazılmıyor). Remote
  `origin` = GitHub, Ozan push etti (origin/main = 92d20c7); ben push etmedim.
- [Q-D25-1] **REST istemcisi sertleştirildi** (67bedd9): API sürümü `config.GEMINI_API_VERSION =
  "v1beta"` ile sabit, her cevap satırına ve results.md metadata'sına yazılıyor · Beklenmeyen cevap
  şeması (aday yok, içerik yok, `usageMetadata` yok, tanınmayan part) → açık `ProviderError`, asla
  sessiz abstain değil · `functionResponse` rolü `FUNCTION_RESPONSE_ROLE` ile ayarlanabilir · 429
  gövdesindeki `RetryInfo`/`QuotaFailure` okunuyor · koşum başında `check_model()`.
- [Q-D25-2] **v2 kırpması** (31f4617, 99a8687): tool şemalarından Pydantic `title`'ları;
  `search_assets`/`find_similar_past_work` çıktısından `top_dense_cosine`/`dense_z` (AgentResult
  trace'inde kalıyor, yalnızca LLM'e gitmiyor) ve `query` yankısı çıktı. `affected_reports` ve
  sahiplik `path`'i dokunulmadı. `PROMPT_VERSION = "v2"`; hash artık sistem prompt'u + tool
  şemalarını kapsıyor (`prompts.model_input_digest`), şema değişikliği de sürüm gerektiriyor.
- [Q-F5] **Soru setleri güncellendi** (1a636af), gold'lar yeniden hesaplandı, veri yeniden
  üretilmedi: (a) ayrım soruları doğal ifadeyle ("Is there an area-manager version of X?"),
  `near_duplicate_by_variant` şablonları; `review_sample.md`'nin tamamı okundu · (b) tek ID'li
  `set_f1` → `contains_all` (`scoring_rule`) · (c) `min_mentioned_count` puanlanmıyor (test bunu
  kanıtlıyor), `review_sample.md`'de ayrı "unscored note" sütunu · Q-F5-2/3/4 aşağıda Kararlar'da.
- [Faz 6 hazırlık] **Teşhis puanları, trivial baseline'lar, ön kayıt** (d617c3c, 097bc0c,
  cce785d). Teşhisler birincil puanı değiştirmiyor: `over_inclusive_rate`, L3/L5 `tool_args_correct`
  (+ doğru çağrıdaki doğruluk = aktarma kaybı), L4 `in_cluster_precision`. jsonl satırları
  `answer_ids`, `evidence_ids`, `abstained` ve tool argümanlarını tutuyor. Baseline'lar (LLM yok,
  test seti, `eval/results/baselines_test.json`): always_abstain L6 1,00 (diğerleri 0) ·
  retrieval_top1 L1 0,47 / L4 0,13 · recorded_owner L2 0,20 · all_heads L5 broadcast 0,00 (n=3) ·
  default_depth_lineage L3 0,60. Ön kayıt results.md'de, test koşumundan önce; metni
  `report.PREREGISTERED_DIGEST` ile sabit (değişirse test kırmızı).
- [Faz 4 canlı adımı] **`pytest -m live` geçti** (2026-09-19, `gemini-3.7-flash`, v1beta, v2):
  dev-L1-01 → `RPT-0169` (doğru; search_assets → get_record → resolve_owner, 8.920 in / 410 out
  token) · dev-L6-01 (maaş) → abstain (doğru; 1 tool, 4.117 in / 478 out). İlk ham istekte 503
  UNAVAILABLE ("model overloaded") geldi → 503 artık `RateLimited("UNAVAILABLE")` olarak geri
  çekilme ile bekleniyor, cevap düşmüyor (c7bf7e5).
- [Faz 4 canlı adımı] **Canlı doğrulama kaydı** (ilk başarılı ham istek/cevap, anahtar maskeli —
  zaten başlıkta gidiyor ve kayda alınmadı — uzun alanlar kesik; dev-L2-01):
  ```
  POST .../v1beta/models/gemini-3.7-flash:generateContent   (x-goog-api-key: ***)
  request:  {"contents":[{"role":"user","parts":[{"text":"Who is the right person to ask about
             Safety Recall Completion by Dealer today?"}]}],
             "generationConfig":{"temperature":0.0},
             "systemInstruction":{"parts":[{"text":"You are MetaCompass, ...[1988 chars]"}]},
             "tools":[{"functionDeclarations":[search_assets, get_record, resolve_owner,
                       trace_lineage, find_similar_past_work, impact_analysis]}]}
  200 {"candidates":[{"content":{"role":"model","parts":[{"functionCall":{"name":"search_assets",
       "args":{"query":"Safety Recall Completion by Dealer"},"id":"call_433568"},
       "thoughtSignature":"EscCCsQC...[440 chars]"}]},"finishReason":"STOP"}],
       "usageMetadata":{"promptTokenCount":1725,"candidatesTokenCount":20,"thoughtsTokenCount":46,
       "totalTokenCount":1791},"modelVersion":"gemini-3.7-flash"}
  2. istek: contents = [user soru, model turu AYNEN (functionCall + thoughtSignature),
            {"role":"user","parts":[{"functionResponse":{"id":"call_433568","name":"search_assets",
             "response":{"hits":[{"id":"RPT-0221",...}, ...5 hit],"signal":{"match_quality":"strong",
             "exact_match":true},"truncated":false}}}]}]
  200 → functionCall resolve_owner {"asset_id":"RPT-0221"} (id "call_602337", yeni imza);
       promptTokenCount 2157, candidates 24 + thoughts 39
  ```
  Doğrulananlar: **functionResponse rolü `"user"` ilk denemede 200** ("function"/"tool" gerekmedi;
  `llm.py`'de yorum olarak da yazıldı) · **thoughtSignature echo'su**: model turu imzasıyla aynen geri
  gitti, model zinciri doğru sürdürdü · **usageMetadata**: `promptTokenCount`,
  `candidatesTokenCount`, `thoughtsTokenCount` geliyor; döngü input = prompt (+toolUse), output =
  candidates + thoughts sayıyor · **429 başlığı**: henüz 429 alınmadı; 200 cevaplarda `Retry-After`
  başlığı yok. Kod hem `Retry-After`'ı hem gövdedeki `RetryInfo.retryDelay`'i okuyor (birim testli);
  canlı 429'da hangisinin geldiği ilk kotada görülecek ve buraya yazılacak.
- [D25 adım 2] **Gerçek token bileşimi** (77a5d6b, dec0e49; `eval/results/input_tokens.json`):
  her kaynak `countTokens` ile (üretim yok) v1 ve v2'nin gönderdiği haliyle sayıldı, token/karakter
  oranı karakter bileşimine uygulandı. Dev sorusu başına (en kısa yol, 2,6 tur):
  | | v1 | v2 |
  |---|---|---|
  | gerçek input token / soru | **5.900** | **5.458** (−%7,5) |
  | chars/4 tahmini | 5.607 | 5.265 |
  | sistem prompt'u | %22 | %24 |
  | tool şemaları | %59 | %57 |
  | tool sonuçları | %16 | %16 |
  | diğer | %2 | %2 |
  chars/4 gerçeğin ~%5 altında (JSON'da token/karakter ~0,25–0,29). İki ölçüm de results.md'de.

- [Faz 6] **Resume hatası düzeltildi** (bedb981): ilk pilot denemesi 30 soruyu da "cevaplanmış"
  sayıp hiç sormadan bitti, çünkü aynı dosyada kuru koşumun (model "fake", prompt v1) satırları
  vardı. Artık bir sonuç dosyası tek bir (model, API sürümü, prompt sürümü) tutuyor; uyuşmazlıkta
  koşum çıkış kodu 2 ile reddediliyor. Kuru koşum dosyası `eval/results/scratch/dry_run/`'a taşındı.
- [Faz 6] Öğrenme notu `docs/learn/10_preregistration_and_baselines.md` (ön kayıt, trivial
  baseline'lar, teşhis puanları).

- [Faz 6 / Dal B] **Model ölçülerek seçildi** (7ce7b41). Kural koşumlardan ÖNCE results.md ön
  kaydına yazıldı (27cfd16): birincil ölçüt agent'ın kendi mekanizmasına kaybettiği cevaplar
  (parse_failure, tool_budget, llm_error + hiç cevaplanamayan soru), ikincil ölçüt dev
  doğruluğu, ve planı 15 günde bitiremeyen model aday değil. Her aday aynı 30 dev sorusunu
  kendi günlük kotasından cevapladı (`eval/model_choice.py`, `--model` bayrağı):
  | model | dev | kayıp | doğruluk | çağrı/cevap | RPD | plan | |
  |---|---|---|---|---|---|---|---|
  | gemini-3.1-flash-lite | 30/30 | 0 | 0,60 | 3,3 | 500 | 5 gün | **seçildi** |
  | gemini-3.5-flash-lite | 30/30 | 3 (tool_budget) | 0,57 | 4,2 | 500 | 6 gün | ikinci |
  | gemini-3.8-flash | 2/30 | 29 | (1,00, n=2) | 5,0 | 20 | 167 gün | aday değil |
  Kategori kırılımı (3.1 / 3.5): L1 2/4 · 2/4 · L2 5/5 · 5/5 · L3 4/4 · 3/4 · L4 0/4 · 0/4 ·
  L5 0/3 · 0/3 · L6 5/6 · 4/6 · MX 2/4 · 3/4. İki Lite adayın L4 ve L5'te aynı şekilde sıfır
  alması, sorunun modelde değil prompt/çıktı sözleşmesinde olduğunu gösterdi.
  `.env`: `LLM_MODEL=gemini-3.1-flash-lite`, `LLM_RPD_LIMIT=500` (RPM 15 ve TPM 1M değişmedi;
  AI Studio TPM vermiyor). Model artık kilitli: test koşumu başladıktan sonra değişirse tüm
  test sonuçları geçersiz olur ve baştan koşulur.
- [Faz 6] **Guard gerçek günlük limiti öğreniyor** (8c8517d): günlük 429'da sunucunun bildirdiği
  değer (yoksa o günün gerçekleşen istek sayısı) `quota_log.json`'a `observed_rpd` olarak
  yazılıyor, sonraki günlerde `.env` ile bunun küçüğü geçerli. 3.8-flash'ta ölçüldü: 20.
- [Faz 6] **Dev iterasyonları bitti: v3, v4, v5 (3/3), dondurulan sürüm v5.**
  `eval/results/prompt_iterations.json` + results.md "Prompt versions and input size":
  | prompt | dev | L1 | L2 | L3 | L4 | L5 | L6 | MX | abstain P/R | çağrı/cevap |
  |---|---|---|---|---|---|---|---|---|---|---|
  | v2 | 0,60 | 2/4 | 5/5 | 4/4 | 0/4 | 0/3 | 5/6 | 2/4 | 0,56 / 0,83 | 3,3 |
  | v3 | 0,80 | 2/4 | 5/5 | 4/4 | 1/4 | 3/3 | 5/6 | 4/4 | 0,83 / 0,83 | 3,5 |
  | v4 | 0,80 | 3/4 | 5/5 | 4/4 | 1/4 | 2/3 | 6/6 | 3/4 | 0,60 / 1,00 | 3,4 |
  | **v5** | 0,77 | 3/4 | 4/5 | 4/4 | 1/4 | 3/3 | 6/6 | 2/4 | 0,67 / 1,00 | 3,6 |
  v4 → v5'te **yalnızca broadcast satırı** değişti, ama L2 (C4 sahiplik) ve MX cevapları da
  değişti; tool sorguları bile farklıydı. Yani sağlayıcı `temperature=0`'da deterministik değil
  ve 30 soruda 1 soruluk fark iki prompt'u ayırmıyor. Bu yüzden dondurma puana göre değil,
  **bilinen şartname boşluğu kalmamasına** göre yapıldı: v5'te `abstained` bayrağı metne bağlı
  (v3'te değildi) ve broadcast'te `answer_ids`'in ne tutacağı tanımlı (v4'te değildi).
  Determinizm bulgusu results.md "Threats to validity"ye girdi; A0'ın üç tekrarının gerekçesi de bu.
- [Faz 6] **Prompt v3 — dev iterasyonu 1/3** (7abb52c). Pilotun hata aileleri:
  (a) **`answer_ids` hijyeni:** model cevabı metinde doğru veriyor ama `answer_ids`'e yola
  çıktığı varlığı (tablo/rapor) koyuyordu — üç L5 sorusunun tamamı, bir MX, bir L4.
  (b) **Erken abstain:** tool'lar konuyla ilgili aday döndürdüğü hâlde parafraz sorularda
  "bulamadım" dedi (üç L4, bir L1).
  (c) Küçükler: tek kelimelik ("report") arama sorgusu; boş formüllü metriğin açıklamasını
  formül sanma; "gelecek yıl kim sahip olacak" sorusuna cevap verme.
  v3 bunlara karşılık: `answer_ids`'in soru tipine göre ne tuttuğunu açıkça yazar, yeni bir
  SEARCH bölümü ekler, ve "metadata bu bilgiyi taşıyamaz" ile "arama kelimesi tutmadı"yı
  ayırır. Sonuç: 18/30 → 24/30 (L5 0→3, MX 2→4, L4 0→1).
- [Faz 6] **Prompt v4 — iterasyon 2/3** (5b912f4): üç cevap "bulamadım" deyip `abstained`'ı
  false bırakıyordu; OUTPUT kuralı bayrağı metne bağladı (L6 6/6, abstain recall 1,00) ve SEARCH
  bir kez daha başka kelimelerle aramayı istedi.
- [Faz 6] **Prompt v5 — iterasyon 3/3** (21eb296): broadcast'te `answer_ids` etkilenen her
  departmanın başkanını tutar. v3'te bu soru yalnızca model gördüğü her başkanı kopyaladığı için
  doğruydu; v4'te daha az kopyalayıp kaybetti. Kural bu şansı ortadan kaldırıyor (L5 3/3).
- [Faz 6] **Retrieval tavanı ölçülüyor** (5b912f4): v3'ün kalan altı hatasının beşinde gold ID'ler
  **hiçbir tool çıktısında yoktu** — retriever cevabı modele hiç göstermedi, yani prompt ile
  düzeltilemez. results.md teşhis tablosunda "Gold never retrieved" sütunu bunu kategori başına
  sayıyor (puanı değiştirmiyor). L4'ün düşük kalması bu tavanla açıklanıyor.
- [Faz 6] **Dev iterasyon tablosu üretilebilir** (`eval/prompt_iterations.py`): results.md'deki
  sürüm karşılaştırması arşivlenen dev koşumlarından hesaplanıyor, elle yazılmıyor. Dosya
  satırlarının prompt sürümü klasör adıyla uyuşmazsa script hata veriyor.

- [Faz 6 / Ozan'ın ara kontrolleri, 2026-09-20]
  1. **Önbellek–tekrar çakışması: DOĞRULANDI, hata yok.** `CachedLLM.key` anahtarın içine
     `salt`'ı alıyor ve runner test setinde `repeat-{n}` veriyor (dev'de sabit "dev"), yani
     r2/r3 r1'in cevaplarını okuyamaz. Kural artık `run_eval.cache_salt()` fonksiyonunda ve
     uçtan uca testli: iki tekrarlı bir koşumda model iki kez çağrılıyor
     (`test_each_repeat_gets_its_own_cache_so_the_spread_is_real`). Silinen satır yok, baştan
     koşum gerekmedi. **Ampirik kontrol (2026-09-21, r2'nin ilk 10 sorusu):** r1 ile metin ve
     tool izi birebir aynı çıktı — Ozan'ın tarif ettiği işaret. Ama çakışma değil, r2 modele
     gitti: (a) aynı ilk çağrı için hem `repeat-1` hem `repeat-2` tuzuyla ayrı önbellek
     dosyaları var, (b) r2 gecikmeleri 2–35 sn (önbellekten oynatma <100 ms), (c) günün istek
     sayısı r1 + r2 LLM adımlarının toplamı (248 + 46 ≈ 288 + ilerleme). Bu 10 soru kısa L1
     aramaları; sıcaklık 0'da aynı cevap makul. Dev'deki determinizm kaybı çok adımlı sorularda
     görülmüştü; kategori bazında ne kadar olduğunu flip_rate gösterecek.
  2. **flip_rate eklendi** (aynı veriden, ek kota yok): üç tekrarın sonucu üzerinde anlaşamadığı
     soruların oranı, kategori başına ve toplamda. results.md'de tam sistem tablosunda std ve
     CI'nın yanında ayrı sütun; ablation açıklaması da oraya bakmayı söylüyor ("flip_rate'in
     yüksek olduğu kategoride tek koşumluk fark okunamaz"). Ön kayıttaki karar kuralı
     değişmedi — flip_rate teşhis, kural değil (ve test sonuçlarına bakılmadan eklendi).
  3. **Demo kotası mekanik olarak ayrıldı:** `QuotaLimits.reserve` + `run_eval.py --reserve N`.
     Guard günlük limitten rezervi düşüyor; rezerve girmek normal temiz duruş (çıkış kodu 0).
     **Plan:** son ablation gününde koşumlar `--reserve 50` ile başlatılır, o günün kalan
     ~50 isteğiyle Faz 7 demo önbelleği (8 hazır soru) üretilir. 8 soru × ~3,5 çağrı ≈ 28
     istek, kalanı yeniden deneme payı.

- [Faz 7, test koşumuyla paralel, 2026-09-21] **API, arayüz, demo önbelleği.** Değerlendirme
  yolundaki koda dokunulmadı (yeni modüller: `service.py`, `api.py`, `app/`, `scripts/`).
  - `api.py` (fee963e): `/health`, `/ask` (yalnız `full`), `/records/{id}`; model yoksa 503, hata
    cevaplarında stack trace yok. `uvicorn metacompass.api:app` yerelde denendi: health v5,
    kayıt dönüyor, olmayan kayıt 404.
  - `service.py`: parçaları süreç başına bir kez kurar; canlı model eval'le aynı sarmalayıcılarla
    (`CachedLLM(QuotaGuardedLLM(...))`). Uygulamanın kota log'u ayrı (`data/app_quota_log.json`):
    commit edilen eval kaydı uygulama denenince oynamasın.
  - **Demo önbelleği** (b850539): 8 soru, hepsi dev setinden (test sorusunu script reddediyor):
    Lookup L1-03 · Ownership L2-03 (C2) · Lineage L3-04 · Past work L4-04 · Impact L5-03
    (broadcast) · Unanswerable L6-01 · Mixed MX-01, MX-02. Dev koşumunun önbelleği birebir
    yeniden oynadı: **modele sıfır istek**, cevaplar v5 dev koşumuyla metin ve iz olarak aynı.
    Son ablation günü için ayrılan 50 istek bu yüzden gerekmedi; pay olarak kalıyor.
  - **Arayüz** (4264f7f): hazır sorular, ID çipleri (`st.pills`, tıklayınca kayıt görüntüleyici),
    abstain / silinen ID uyarıları, ajan izi. Hazır cevaplarda toplam süre ve model adımlarının
    süresi gösterilmiyor (önbellekten oynatma süresi agent hakkında bir şey söylemez; tool
    adımları gerçekten çalıştığı için onlarınki kalıyor). Serbest metin yalnızca model varsa açık:
    oturumda 5, günde `DEMO_DAILY_LIMIT`. Kenar çubuğu hazır soruların **doğru cevaplanmış dev
    soruları** olduğunu ve ölçülen doğruluğun results.md'de olduğunu söylüyor. Tarayıcıda
    elle kontrol edildi.
  - Test hijyeni: önbellek yazan testler (API, runner, demo) artık veri kümesinin kopyasını
    kullanıyor (`writable_data_dir`); determinizm testi paylaşılan kümedeki her dosyayı
    hash'liyor ve bir önbellek dosyası onu düşürüyordu.
  - `docs/architecture.md` (71dac7d), öğrenme notu `docs/learn/11_serving_the_agent.md`.
  - Faz 7'nin insan kontrol noktası (Ozan arayüzü dener) CLAUDE.md gereği Faz 8 raporuna
    birleşiyor.
- [Faz 8, yerel kısım, 2026-09-21] (9801b41) `Dockerfile`: `python:3.13-slim`, uid 1000
  kullanıcısı (HF Spaces'in çalıştırdığı kullanıcı; her `COPY --chown`), `requirements.txt`'nin
  `+cpu` torch pini, CI gibi editable kurulum (`config.PROJECT_ROOT` kaynak konumundan
  türüyor), derlemede `scripts/warm_up.py` (seed 42 verisi + embedding modeli + belge
  embedding'leri), port 7860, imajda anahtar yok. `deploy/hf_space_README.md`: Space README
  şablonu (`sdk: docker`, `app_port: 7860`; HF dokümanından doğrulandı). Statik testler
  (`test_docker.py`): `.env`, `docs/plan`, `docs/learn`, `data` imaja girmiyor, root olarak
  kopyalama yok, anahtar gömülü değil.
  **Bekleyen:** yerel `docker build`/`run` ve imaj boyutu — Docker Desktop motoru çalışmıyor
  (kendim başlatmadım). Temiz venv'de `requirements.txt` kurulumu — paket indirmesi, onay
  bekliyor. Deploy/push — onay bekliyor.

- [V0, 2026-09-21] **Donmuş ağaç parmak izi** (50594e4). `runinfo.frozen_tree_hash`: `agent`,
  `tools`, `retrieval`, `data` (vocab dahil), `graph.py`, `config.py`'nin eval sabitleri (AST ile:
  büyük harfli sabitler, `AgentConfig`, `output_char_cap`, varsayılan embedding modeli; yol
  sabitleri ve uygulama ayarları hariç) + **geçici karar:** `eval/configs.py`, `eval/scoring.py`,
  `eval/test_set.json` (koşum ortasında değişirlerse ölçüm aynı şekilde bölünür; fc05ccc'den beri
  üçü de aynı). Runner her satıra yazıyor ve farklı hash'li dosyaya eklemeyi reddediyor.
  **Ölçüm:** fc05ccc = `b4025ab1103ea7c9`; b1eed88 ve sonrası = `5f0ee29ab437ea65`. Tek fark
  `agent/quota.py`'deki demo rezervi (b1eed88, test koşumu ortasında benim eklediğim):
  `QuotaLimits.reserve`, `daily_limit()`'te `- reserve`, bir hata mesajı. Eval koşumlarında
  `reserve=0` idi; `daily_limit` her durumda aynı değeri, mesaj aynı metni veriyordu; guard
  yalnızca isteğin *ne zaman* gideceğine karar veriyor, cevabın ne olacağına değil. Ozan'ın
  talimatıyla rezerv kaldırıldı → `quota.py` ve testleri fc05ccc ile bayt bayt aynı, ağaç
  hash'i yine `b4025ab1103ea7c9`. Geriye dönük: her satıra **üretildiği commit'in** hash'i
  yazıldı (`frozen_tree_hash_backfilled: true`): r1'de 23 satır `b4025ab…` + 77 satır
  `5f0ee29…`, r2'de 81 satır `5f0ee29…`. Runner r1'i reddediyor (denendi, istek harcanmadı) →
  **Q-V0-1.**
- [Q-V0-1, 2026-09-22] **Önbellekten yeniden oynatma ile eşdeğerlik kanıtı (Ozan'ın (c) kararı).**
  `run_eval.py --cache-only` (128acfb): sağlayıcı yok, ağ yok; önbellekte olmayan ilk istek o
  soruyu "replay_miss" yapar ve koşum sürer (miss, `QuotaExhausted` alt sınıfı: donmuş döngü onu
  yeniden denemeden geçirir; döngüye dokunulmadı). Donmuş ağaçla (`b4025ab…`) A0 r1 ve r2 aynı
  tuzlarla (repeat-1/2) önbellekten yeniden oynatıldı, **kota harcanmadı**. Karşılaştırma
  (`eval/verify_replay.py`; cevap metni, `answer_ids`, `evidence_ids`, `abstained`,
  `stopped_reason`, her tool çağrısı ve argümanları, çağrı sayısı, token sayıları; süreler ve
  tarihler hariç): **158 satırın 158'i birebir aynı, 0 fark, 0 ıskalama.** Kontrol grubu:
  dondurma koduyla üretilmiş 23 satır da birebir aynı. Satırlar orijinal hâliyle kaldı (süreler
  dahil; yeniden oynatma süresi p50/p95'e girmez), yalnızca `frozen_tree_hash` → `b4025ab…`,
  eklenen alanlar `equivalence: cache_replay_verified` ve `frozen_tree_hash_produced: 5f0ee29…`
  (köken kaybolmasın diye; Ozan'ın listesine ek). Sayılar
  `eval/results/replay_verification.json`'da; results.md "Threats to validity"deki satır bu
  dosyadan üretiliyor. **V6 yeniden: PASSED** (181 cevap). Koşum kaldığı yerden devam ediyor.
- [Faz 6, 2026-09-22] **A0 ×3 tamamlandı: 300/300 cevap** (r2'nin kalan 19'u + r3'ün 100'ü,
  bugün 408 istek). V6: PASSED, llm_error 0. A1 aynı gün kalan kotayla başladı: 49/100, gün 499
  istekle kapandı; V6 gün sonu: PASSED (349 cevap). Puanlar koşumlar bitene kadar okunmuyor.
  Kalan plan: A1 51 · A2 100 · A4 100 · A3 40 · A5 25 = 316 cevap ≈ 2,3 gün.
- [Q-F8-2 / V11, 2026-09-22] **Hafif demo profili** (6f67862). Serbest metin kapalıyken demo arama
  yapmıyor: 8 cevap önbellekten, kayıt görüntüleyici yalnızca `get_record`. Bu yüzden
  `service.build_demo_components` yalnızca store + graf + kayıt aracını kuruyor (retriever ve
  embedder yok) ve veri yoksa ilk kullanımda üretiyor (seed 42); ajan ve model istemcisi yalnızca
  canlı soru yolunda import ediliyor; uygulama paket kurulu değilse `../src`'yi yola ekliyor.
  Donmuş yola dokunulmadı (hiçbir modül import anında torch yüklemiyordu, ölçüldü).
  `app/requirements.txt` (ölçülen gerçek ihtiyaç, `requirements.txt` sürümleriyle): streamlit,
  pandas, numpy, pydantic, networkx, Faker, rank-bm25, python-dotenv. Streamlit Community Cloud
  bağımlılık dosyasını önce giriş dosyasının klasöründe arıyor (dokümandan doğrulandı), yani bu
  dosya kökteki ağır `requirements.txt`'nin önüne geçiyor. Yerel paket kurulumu belgelenmemiş →
  `src` yol eklemesi. Python: desteklenenler güvenlik güncellemesi alan sürümler, varsayılan
  3.12; **3.13** seçildi (CI/yerelle aynı). Test: taze yorumlayıcıda boş veri klasöründen hazır
  cevap + kayıt görüntüleyici → torch / sentence_transformers / transformers yüklenmiyor.
  **V11** (`scripts/check_demo_profile.py`): HEAD'in arşivi, yalnızca `app/requirements.txt` ile
  temiz venv → kurulum **143 sn**, venv **390 MB** (tam kurulum 1,4 GB) · AppTest: 8 hazır soru,
  kayıt görüntüleyici çalışıyor, serbest metin kutusu yok · ağır paketler ne yüklü ne kurulu ·
  gerçek Streamlit: sağlık **3,0 sn**'de, sayfa hemen · tarayıcıda çizim ve bir hazır soru
  doğrulandı. **PASSED.**
- [V8, 2026-09-22] **Streamlit Community Cloud: https://metacompass.streamlit.app** (Ozan dağıttı,
  Python 3.13, secrets boş). Tarayıcıda: sayfa açılıyor (uygulama bir iframe'de, `/~/+/`) ·
  **8 hazır sorunun 8'i** doğru soruyu ve cevap kartını gösteriyor, her biri 0,37–0,50 sn'de,
  ajan izi hepsinde var, Unanswerable'da abstain uyarısı çıkıyor · **kayıt görüntüleyici**:
  `RPT-0068` çipi 1,4 sn'de kaydı açtı (ilk kullanımda veri üretimi dahil olabilir) ·
  **serbest metin kutusu yok**, "yerelde kendi anahtarınla çalıştır" yönlendirmesi var ·
  **ilk açılış**: uyanık uygulamada sayfadan uygulamanın çizilmesine 4,0 sn; günün ilk
  ziyaretinde dış sayfa 13,8 sn'de yüklendi, uygulama ~30 sn içinde çizildi (tam ölçülemedi).
  **Uyku/uyanma** (Streamlit dokümanı): 12 saat trafik yoksa uyur; ziyaretçi "Yes, get this app
  back up!" butonuyla uyandırır (herkes uyandırabilir); uyanma süresi belgelenmemiş, uygulama ilk
  uyuduğunda ölçülecek. Uyanınca `data/` yeniden üretilir (ilk kayıt görüntülemesinde ~2 sn) —
  tasarım gereği. Tarayıcıda buton etiketleri gizli bölmede geç çiziliyor; DOM'da etiketler yerinde.
- **Ders (2026-09-22):** Donmuş yola koşum sırasında giren değişikliği (benim eklediğim demo
  rezervi) V0 mekanizması yakaladı. Mekanizma olmasaydı bu fark hiç görülmezdi: kod davranışça
  etkisizdi, testler yeşildi, satırlar sıradan görünüyordu. Kanıt ise argümanla değil ölçümle
  geldi: önbellek anahtarı isteğin tamamını içerdiği için yeniden oynatma, "aynı kod aynı
  istekleri üretiyor mu" sorusunu sıfır kotayla ve bire bir cevaplıyor. Kural: test koşumu
  bitene kadar donmuş yola hiçbir değişiklik yok; altyapı ihtiyacı varsa donmuş yolun dışına.
- [V1, 2026-09-21] `check_all --slow`: yeşil. Son ağaçta (1a9ea81): **573 test** (yalnız `live`
  hariç), kapsam **%99** (1.715 satırın 22'si), 251 sn.
- [V4, 2026-09-21] Determinizm: sıfırdan iki üretim bayt bayt aynı; **eval'in kullandığı
  `data/` sıfırdan üretimle aynı**; taze veriden yeniden üretilen data card commit'lenmiş
  `docs/data_card.md` ile birebir aynı. Hash'ler (sha256 ilk 16): `_meta.json` da787003e393a91d ·
  employees 3d602794b01e45c1 · metrics 2d2373ca17b12e56 · report_table_edges bce30d60af696a19 ·
  reports 852b83e0c094dd1a · requests e298121e2f2a98d5 · table_table_edges 4feb6052639c4357 ·
  tables 60cd673b7173ed53.
- [V5, 2026-09-21] Docker (motor açıktı): derleme **405 sn** (soğuk, indirmeler dahil), imaj
  **2,69 GB**. `.env` olmadan `docker run -p 7860:7860`: `/_stcore/health` → `ok` 4 sn'de, `/` →
  200, ilk sayfa tarayıcıda 2,3 sn'de çizildi, hazır cevap 369 ms. Konteyner içi
  `scripts/smoke_check.py`: 7 tablo, embedding önbelleği, 8 hazır cevap, `get_record` → PASS.
  `id` → uid=1000(user). `ls`: `.env`, `docs/plan`, `docs/learn` yok. Serbest metin kutusu yok,
  "yerelde kendi anahtarınla" yönlendirmesi var.
- [V6, 2026-09-21] `scripts/audit_eval.py` (12ee4cb): dosya başına tek kimlik, dosya adıyla
  uyuşma, tekrarlı soru yok, her saklanan puan yeniden puanlamayla aynı, kota tutarlılığı (bir
  günün satırlarındaki model çağrısı o günün isteklerini belirgin aşarsa → paylaşılan önbellek
  işareti). `report.py` denetim kırmızıyken results.md yazmıyor. **Sonuç:** 181 cevap, 181 puan
  yeniden üretildi, tekrar yok, kota tutarlı, llm_error 0; tek FAIL: r1'de iki kimlik (Q-V0-1).
- [V7, 2026-09-21] `scripts/scan_history.py` (169ce52): tüm referanslardan erişilen her blob,
  her commit mesajı, her yol; sır desenleri, yasaklı terimler ve `.env`'deki anahtarın kendisi.
  99 commit: **temiz.** Hiçbir bulguda değer yazdırılmıyor.
- [V2, 2026-09-21] Temiz venv: HEAD'in `git archive` çıktısı geçici klasöre (ZIP indirmesi gibi:
  `.git`, `.env`, `data` yok) → yeni venv → `requirements-dev.txt` → `pip install -e .` → veri →
  `check_all`. Kurulum **562 sn**, venv **1,4 GB**, veri üretimi tamam. Bulgu: git'siz ağaçta
  Space hazırlık testleri (3) düştü ve sır taraması git traceback'iyle çöktü — ikisi de dosyaları
  git ile listeliyordu. Düzeltme (1a9ea81): hazırlık git yoksa klasörü (bytecode hariç) kullanır;
  taramalar `NotAGitCheckout` verir, kapı bunu gerekçesiyle FAIL sayar (listeleyemediği ağaca
  onay veremez). Düzeltmeyle aynı ağaçta: **569 test geçti**, kapsam %98, yasaklı terim taraması
  terimler dosyası olmadığı için atlandı (tasarım gereği, `docs/plan` commit edilmez), sır
  taraması "git deposu değil" diye FAIL. Tam yeşil kanıt V3'te (klon).
- [V3, 2026-09-21] **GitHub'dan temiz klon** (e7860b4) → aynı adımlar, `.env` yok: kurulum
  **539 sn**, venv 1,4 GB, veri üretildi, `check_all` **PASSED**: 569 test (live seçilmedi),
  kapsam %98, sır taraması temiz (156 dosya), yasaklı terim taraması terimler dosyası olmadığı için
  atlandı (tasarım gereği). Repo başkasının makinesinde çalışıyor.
- [Faz 8, 2026-09-21] **HF Docker Space reddedildi (402 Payment Required):** "Static Spaces are
  free for everyone, but hosting Gradio and Docker Spaces on free cpu-basic requires a PRO
  subscription." Hiçbir şey oluşturulmadı. README'deki demo linki kaldırıldı (a75296a) —
  var olmayan Space'e link verilmesin → **Q-F8-2.**
- [Faz 8, 2026-09-21] Space'te model anahtarı yok (Ozan): anahtar yokken serbest metin kutusu hiç
  görünmüyor, yerine README'nin "Run it locally" bölümüne yönlendirme var (321f4e9).
  `scripts/deploy_space.py`: yalnızca uygulamanın ihtiyacı olan dosyalar + Space README'si,
  `huggingface_hub` ile, token login önbelleğinden. Demo rezervi kaldırıldı (V0 ile birlikte).
- [Faz 9, 2026-09-21] README taslağı (84d044d): §16 yapısı; sonuç tablosu işaretli blokta,
  yalnızca `report.py --readme-snippet` yazar, `--check-readme` (V9) elle değiştirilmiş sayıyı
  yakalar. Koşumlar bitince dolacak.

- [Faz 6, 2026-09-23] **Sağlayıcı aşırı yüklü (503), kota değil.** Günün ilk koşumu hiç cevap
  üretemeden durdu: "still rate limited after 5 retries". Tek ham istekle bakıldı: HTTP **503**,
  "This model is currently experiencing high demand." Yani günün 500 isteği el değmemiş; guard
  503'ü geçici kota gibi ele alıp 1-2-4-8-16 sn geri çekiliyor ve 5 denemede pes ediyor
  (`quota.py` donmuş, koşum bitene kadar dokunulmuyor). İki düzeltme donmuş yolun dışında:
  runner artık "kota doldu" ile "sağlayıcı reddetti"yi ayrı yazıyor (`stop_message`, testli) ve
  günlük koşum sarmalayıcısı 503'te günü bırakmak yerine 10 dakikada bir yeniden deniyor.
  Kota kaydında yeni gözlenen limit: `GenerateRequestsPerMinutePerProjectPerModel-FreeTier` = 15.

- [Faz 6, 2026-09-23] **Ablation'lar tam sistemin önbelleğinden cevap alıyordu; düzeltildi ve
  etkilenen satırlar silindi.** Önbellek tuzu yalnızca tekrarı içeriyordu (`repeat-1`), yani A0 r1,
  A1 r1 ve A2 r1 aynı tuzu paylaşıyordu. A1 yalnızca retrieval modunu değiştirdiği için ilk isteği
  A0'ınkiyle birebir aynı; tool çıktıları da aynı çıktığında bütün konuşma önbellekten geliyordu.
  **Ölçüm:** A1'in 63 cevabının **49'unda tool izi A0 r1 ile birebir aynı**, 20'sinde cevap metni de
  aynı; bazı cevaplar 42–140 ms sürmüş (ağ yok). Üstelik bu eşitsizdi: A3/A4/A5 farklı prompt veya
  tool listesi kullandığı için paylaşamıyordu. Karar (puanlara bakmadan, yapısal gerekçeyle):
  `cache_salt` artık konfigürasyonu da içeriyor (`A1-repeat-1`), her konfigürasyon kendi cevabını
  modelden alıyor; testle sabitlendi (9a1a84e). Paylaşılan tuzla üretilmiş satırlar silindi: A1 65,
  A2 1, A4 1. A0'ın 300 satırı etkilenmedi: tekrarların tuzları zaten ayrıydı ve A0 kaynak taraftı
  (r1↔r2 karşılaştırması da ayrı önbellek dosyaları ve gerçek gecikmelerle doğrulanmıştı).
  Maliyet: A1 ve A2 yeniden koşulacak (~250 istek), günün kotasından karşılanıyor.
  **Ders:** Önbellek anahtarı "aynı girdi" demektir; ama ölçümde iki koşumun aynı girdiden aynı
  cevabı *paylaşması* ile her birinin kendi cevabını *çekmesi* farklı şeylerdir. Kota tasarrufu
  ile bağımsız örnekleme çatıştığında ölçüm kazanır.

- [Faz 9, 2026-09-23] **Demo GIF'i ekran kaydı olmadan üretildi.** Kareler barındırılan demodan
  script'le alınıyor (`scripts/capture_frames.py`), GIF'i Pillow kuruyor
  (`scripts/build_demo_gif.py`, 7 test). Ayrıntı ve iki tıkanmanın çözümü: "Demo GIF" bölümü.
  Sığan ayar: tam genişlik 1280×720, 3 ara kare, 256 renk → **0,67 MB** (sınır 5 MB).
  Yan ürün: uygulamada derin bağlantılar (`?q=`, `&trace=open`, `&record=`), b646c06.

- [Faz 8, 2026-09-24] **V12 — önbellek izolasyon denetimi** (`scripts/audit_cache_isolation.py`,
  12 test). Her konfigürasyon için: cevap · sağlayıcıya giden istek · istek/cevap · medyan
  gecikme · hiç istek harcamamış cevap · 500 ms altı cevap. **FAIL koşulu:** bir config'in
  istek/cevap oranı A0'ınkinin yarısının *altındaysa*. `report.py` sayfayı bu denetim yeşil
  olmadan yazmıyor (V6'dan hemen sonra), sayılar da sayfaya "Each configuration answered from
  the model (V12)" bölümü olarak giriyor; ayrıca "Threats to validity"de tuz olayının ne
  olduğu ve 67 satırın silinip yeniden koşulduğu yazıyor.

  **İsteği nasıl sayıyorum.** Satırlarda "şu çağrı önbellekten geldi" diye bir alan yok, ama
  önbellekten dönen çağrı ağa çıkmıyor. Ölçüm: bugüne kadarki bütün `llm` adımlarında en yavaş
  önbellek çağrısı 19 ms, ağa çıkan en hızlı çağrı 658 ms. Eşik bu boşluğun içinde: 50 ms.
  Bu iki uç her koşumda yeniden ölçülüp rapora yazılıyor, yani "boşluk geniş" iddiası zamanla
  sessizce yanlışlanamıyor.

  **Ozan'ın çerçevesine düzeltme: "aynı iz = sızıntı" değil.** Bağımsız koştuğu kanıtlı A1 ile
  A0, karşılaştırılabilir 100 sorunun **77'sinde** birebir aynı tool izini veriyor. Sebep
  yapısal: A1 yalnızca retrieval modunu değiştiriyor, modelin ilk isteği A0'ınkiyle bayt bayt
  aynı, kolay sorularda aynı argümanla aynı çağrı geliyor. Yani iz payını FAIL koşulu yapsaydım
  denetim her gün kırmızı yanardı ve kapatılırdı. İz payı raporlanan bir sayı, karar veren
  ölçüt istek/cevap oranı.

  **Günün dersi.** Mekanizma (tuz) doğru kurulmuştu, kapsamı eksikti: anahtar "aynı girdi"yi
  kapsıyordu ama "aynı ölçüm birimi"ni kapsamıyordu. Dikkati ilk çeken şey imkânsız gecikmelerdi
  (42–140 ms), ama bu göz kararı bir fark etme; **kendi kendine koşan ölçüt istek/cevap oranı**,
  çünkü bir config'in modele gerçekten gidip gitmediğini tek başına gösteriyor. Bundan sonra her
  yeni koşum tipinde (yeni config, yeni set, yeni model) ilk bakılan sayı bu oran.

- [Faz 8, 2026-09-24] **"Gold never retrieved" sayısı yanlıştı; kotasız düzeltildi.** İz, her
  tool çıktısının yalnızca ilk **300 karakterini** saklıyor. "Gold hiç getirilmedi" bunun üzerinden
  okunuyordu, yani modelin gerçekten okuduğu bir payload'ın aşağısındaki ID "hiç getirilmedi"
  sayılıyordu. **Ölçüm:** tam sistemin 66 yanlış cevabının 57'si aramaya yıkılıyordu; gerçek sayı
  **45**. En büyük saptırma L5'te: 12 hatanın 12'si "retrieval tavanı" görünüyordu, hiçbiri değil —
  model ihtiyacı olan herkesi görmüş, cevabına fazladan kişi eklemiş (**12/12 fazla kapsayıcı**).
  Yani o kategoride sorun arama değil, cevabın kapsamı. Çözüm `scripts/replay_tool_outputs.py`:
  saklı tool çağrılarını (ad + argüman tam duruyor) aynı registry'den yeniden çağırıp modelin
  gördüğü ID'leri kaydediyor. Deterministik, kota harcamıyor, dönen payload agent'ın modele
  ilettiğinin aynısı (çıktı üst sınırı dahil). Neden izdeki kısaltmayı büyütmedim: `agent/` donmuş
  yolda ve büyütmek yalnızca gelecek satırları düzeltirdi, elimdeki 500 satırı değil.
- [Faz 8, 2026-09-24] **Hata analizi yeniden yazıldı.** Her yanlış cevap altı türden birine
  giriyor: eksik abstain · gereksiz abstain · yanlış tool/argüman · retrieval tavanı · fazla
  kapsayıcı · doğru tool yanlış yorum. Sıra bir **neden iddiası**: yanlış düğüme lineage çağrısı da
  gold'u göstermez, o yüzden yanlış çağrı tavandan önce okunuyor; tersi olsaydı her yanlış çağrı
  tavanın arkasına saklanırdı. Örnekler kategori başına 3 ve **tür çeşitliliğine göre** seçiliyor
  (ID sırasında ilk üç, L1'de aynı türü üç kez gösteriyordu). Her ablation'a tek cümle: ne katıyor,
  fark A0'ın tekrar std'si ve flip_rate karşısında ne anlama geliyor.
- [Faz 8, 2026-09-24] **`scripts/day_end.py`** — gün sonu rutini tek komut: V6 · V12 · replay ·
  results.md · V9 · V7. Sıra testle sabit (sayfa, çelişmemesi gereken denetimlerden ve sayılarını
  bastığı replay'den sonra yazılıyor). Push ve commit yapmıyor: kırmızı bir kontrolün ne anlama
  geldiği karar, script'in işi onu görünür kılmak. `--final` ile V10 --final de ekleniyor.
  Koşum sürerken replay dosyası doğal olarak geride kalıyor; sayfa bunu satır sayısıyla **söylüyor**,
  sessizce eski yönteme düşmüyor, ve `check_report --final` eksik replay'li bir final sayfayı
  reddediyor.

- [Disiplin ihlali, 2026-09-25] **Koşum bitmeden kısmi test puanlarını gördüm.**
  `eval/report.py --check-readme`'yi "snippet mekanizması hâlâ çalışıyor mu" diye çalıştırdım;
  çıktı farkları satır satır bastığı için A2/A3/A4'ün kısmi kategori puanları ekrana geldi.
  Niyet bu değildi ama sonuç bu. **Ne yapmadım:** o andan sonra sistemde hiçbir değişiklik yok —
  prompt, eşik, config, donmuş yol hepsi aynı; `frozen_tree_hash` `b4025ab1103ea7c9` olarak
  duruyor ve zaten değişseydi runner yeni satır yazmayı reddederdi. **Ders:** "sonuçlara bakma"
  disiplinini yalnızca niyetle değil, komut seçimiyle korumak gerekiyor; `--check-readme` sonuç
  tablosu basan bir komut ve koşum sırasında çalıştırılmamalı. Gün sonu rutininde yok, oraya da
  eklenmeyecek; yalnızca final adımında koşulacak.

## Devam eden
- Görev: **test koşumu** (dondurulmuş yapılandırma, `fc05ccc`). Sıra: A0 ×3 → A1, A2, A4 →
  A3, A5 → `eval/report.py` → hata analizi → threats to validity.
  Durum 2026-09-20: `test_A0_r1.jsonl` 23/100, gün kotayla kapandı. Yarın aynı komut:
  `python eval/run_eval.py --set test --config A0 --repeat 3`.
  Günlük 500 istek ≈ 140 cevap, 665 cevap ≈ 5 gün. Demo önbelleği kota harcamadan üretildi,
  bu yüzden son ablation gününde `--reserve` artık şart değil (mekanizma duruyor).
  Durum 2026-09-21 sonu: `test_A0_r1` 100/100, `test_A0_r2` 81/100; gün kotayla kapandı.
  Guard 486 istek saydı, sunucu 500'de kesti: fark, yanıtsız kalan denemeler (503 bekleme
  denemeleri, bir `OSError`) — guard yalnızca cevaplanan istekleri sayıyor.
  Tek geçici hata: r2 L4-001'de bir model çağrısı 2,8 sn sonra `OSError(22)` ile düştü, döngünün
  yeniden denemesi ikinci seferde geçti; iz bunu `error: OSError` adımı olarak gösteriyor.
  Tahmin: A0 yarın biter (19 + 100 = 119 cevap ≈ 420 istek), sonra A1.
  Durum 2026-09-24 sonu: **A0 300/300 · A1 100/100 · A2 100/100 · A4 23/100.** Gün 500 istekle
  kapandı. Kalan: A4 77 · A3 40 · A5 25 = 142 cevap ≈ 455 istek, yarının kotasına sığması bekleniyor.
  Gün sonu rutini yeşil (V6 · V12 · replay · results.md · V9 · V7).
  Durum 2026-09-25 sonu (sıra Ozan'ın kararıyla A3 → A5 → A4): **A3 40/40 · A5 25/25 bitti,
  A4 83/100.** Kalan: **A4 17 cevap**. Rapor üretilmedi (Ozan: kota son cevaba yetmezse rapor yok),
  gün sonu rutini yeşil.
  **Oran tahmini ve düzeltmesi.** A3 ilk 10 cevapta 4,40 → 40 cevapta **4,85** istek/cevap
  (`resolve_owner` yok, model zinciri kendi yürüyor; 40 cevabın 4'ü tool bütçesine takıldı).
  A5 için "o da bir tool kaybediyor, oran benzer çıkar" dedim; **yanlış çıktı: 3,92**, ve ilk 10
  cevapta 3,10'du. Kesilme değil: A5'in 25 cevabının hiçbiri tool bütçesine takılmadı, ortalama
  tool çağrısı 2,18 — aynı kategorilerde A0'ın 2,76'sının altında. Yani `impact_analysis` yokken
  model zinciri kurmak yerine daha kısa yoldan cevaplıyor. Cevabın kalitesine etkisi puan sorusu,
  koşum bitmeden bakılmadı. Ders: "tool'u kaldırınca model daha çok çalışır" bir varsayım, kural
  değil; ablation maliyetini komşu ablation'dan değil kendi ilk cevaplarından tahmin et.
  Durum 2026-09-23 sonu: A0 300/300 tamam. Paylaşılan önbellek tuzuyla üretilmiş A1/A2/A4
  satırları silindikten sonra A1 yeni tuzla baştan koşuldu: **`test_A1_r1` 97/100**, gün
  kotayla kapandı (320 istek, 810k token; guard'ın saydığı istekler). Gün içinde sağlayıcı bir
  kez de "aşırı yüklü" dönemine girdi, ilk deneme kota harcamadan durdu, 600 sn sonraki ikinci
  deneme geçti. Kalan plan: A1 3 · A2 100 · A4 100 · A3 40 · A5 25. Denetim (V6) yeşil,
  `test_A1_r1` tek kimlik taşıyor, `frozen_tree_hash` hâlâ `b4025ab1103ea7c9` (bugünkü
  değişiklikler app/scripts/tests/README'de, dondurulmuş yola dokunmadı).
- Disiplin: test satırlarının puanlarına koşum bitene kadar bakılmıyor, sistemde hiçbir değişiklik
  yapılmıyor (spec §9.1: test sonucuna bakıp prompt/eşik değiştirmek yasak). Kayıt ediliyor,
  okunmuyor.

## CV maddesi (son hâline yakın; rakamlar yalnızca results.md'den, koşumlar bitince)

> **MetaCompass — BI Metadata Agent** · [GitHub](https://github.com/ozandokur/metacompass) ·
> [Demo](https://metacompass.streamlit.app)
> *Python · BM25 + dense retrieval (RRF) · NetworkX · FastAPI · Streamlit · Docker · Gemini API*
> - Built a framework-free, six-tool LLM agent that answers ownership, lineage and
>   change-impact questions over a synthetic BI catalog, with deterministic multi-hop ownership
>   resolution and a grounding guard that strips any ID no tool returned.
> - Designed a 100-question evaluation with independent gold answers and deliberately
>   unanswerable questions; pre-registered the reading rules and reported per-category accuracy
>   with bootstrap CIs, abstention precision/recall and leave-one-out ablations
>   {A0 genel doğruluk ± std ve bir ablation bulgusu: results.md'den}.
> - Ran the whole study on a free-tier LLM quota: chose the model by a pre-registered
>   measurement, fingerprinted the measured code on every result line, and proved a mid-run
>   infrastructure change harmless by replaying all affected answers from the LLM cache.

## GitHub "About" önerisi (Ozan girecek)

- **Description:** A tool-using LLM agent for BI metadata — ownership, lineage and change
  impact — that knows when to abstain. Synthetic data, pre-registered evaluation.
- **Website:** https://metacompass.streamlit.app
- **Topics (8):** `llm-agent` · `tool-calling` · `hybrid-search` · `data-lineage` ·
  `metadata-management` · `llm-evaluation` · `streamlit` · `python`

## Demo GIF (`assets/demo.gif`) — üretildi, 2026-09-23

Ekran kaydı yok: kareler `scripts/capture_frames.py` ile barındırılan demodan alınıyor,
`scripts/build_demo_gif.py` (Pillow) bunları GIF'e çeviriyor. İkisi de yeniden çalıştırılabilir.

**Kareler** (`assets/frames/NN_ad.png`, hepsi 1280×720, 60–77 KB):

| kare | adres | karede görünmesi gereken |
|---|---|---|
| 01_start | `/` | boş ana sayfa, kenar çubuğunda 8 hazır soru |
| 02_impact | `?q=impact` | "60 reports", Answer çiplerinde başkanlar (EMP-031 dahil) |
| 03_trace | `?q=impact&trace=open` | Agent trace açık: `search_assets` → `impact_analysis` |
| 04_record | `?q=impact&record=EMP-031` | Record EMP-031, "Head of Aftersales" |
| 05_abstain | `?q=unanswerable` | sarı "Abstained: the metadata does not hold this answer." |

Her kare için script, o karenin göstermesi gereken metin sayfada belirene kadar bekliyor
(`document.body.innerText`), sonra ilgili bölümü kadraja kaydırıyor. Böylece "etiketler geç
çizilmiş" kare üretmiyor; metin gelmezse hata veriyor.

**İki tıkanma ve çözümü.** (1) Baş bölgesiz Edge'in `--screenshot`'ı Streamlit'i yarım
çiziyor, çünkü sayfa websocket üzerinden doluyor; çözüm tarayıcıyı DevTools protokolü
üzerinden sürmek (websocket istemcisi `websockets`, zaten pinli; tornado artık Streamlit
bağımlılığı değil). (2) Streamlit Community Cloud asıl uygulamayı `/~/+/` adresindeki bir
iframe'e koyuyor; dış kabuğun `body`'si boş. Script iç adresi kullanıyor: hem metin okunuyor
hem de kareler Cloud çubuğu ve rozeti olmadan yalnızca uygulamayı gösteriyor.

**Kareleri elde etmek için uygulamaya derin bağlantı eklendi** (`?q=`, `&trace=open`,
`&record=`; b646c06). Yan faydası: bir cevabın durumu paylaşılabilir hâle geldi. URL oturumda
bir kez okunuyor, sonraki tıklamalar URL'ye geri sıçramıyor.

**GIF ayarı.** Merdiven: tam genişlik → 1100 → 960 → daha az ara kare → daha küçük palet.
**En üst basamak sığdı: tam genişlik (1280×720), gap başına 3 ara kare, 256 renk → 0,67 MB**
(sınır 5 MB). Süreler 1200 / 2500 / 2500 / 2500 / 3000 ms, ara kareler 80 ms, toplam 12,66 sn,
17 kare, `loop=0`, `optimize=True`. Palet tek ve ortak (kare başına palet renk titremesi
yapardı), dither kapalı: düz arayüz görüntülerinde hem yanlış görünüyor hem de GIF'in
sıkıştırdığı düz alanları bozduğu için dosyayı büyütüyor.

Testler (`tests/test_build_demo_gif.py`, 7 test): kareler yerinde ve sırada · **farklı boyutlu
kare `FrameSizeMismatch` ile reddediliyor, sessizce yeniden boyutlandırılmıyor** · zaman
çizelgesi her kareyi kendi süresince tutuyor · ara kare sayısı ayarı çizelgeyi kısaltıyor ·
üretilen dosya GIF, sonsuz döngü, sınırın altında · hiçbir basamak sığmazsa `TooBig`.

## Kararlar ve gerekçeleri
- 2026-09-23 · **Ozan: GIF'i ekran kaydıyla değil, alınan ekran görüntülerinden üret.** Beş
  durum, sabit 1280×720, hepsi aynı boyutta; boyut farkında script hata versin, sessizce
  yeniden boyutlandırmasın. Gerekçe (benim okumam): ekran kaydı her tekrarda başka çıkar ve
  elle düzeltilir; kare + script yeniden üretilebilir ve tek kare değiştirilebilir. Uygulama
  tarafındaki bedeli derin bağlantılar oldu — tıklama zinciri yerine adres.
- 2026-09-23 · **Ozan: video yok (şimdilik).** README ve CV maddesinde video linki/yeri
  bulunmuyordu, spec'ten çıkarıldı (Faz 9 görev 4, §16 şablonu, faz tablosu, §19 listesi).
  Yerine: koşumlar bitince README'nin son hâli ve rakamlı CV maddesi hazırlanacak, sonra DUR.
  GIF'i Ozan koyacak; `assets/demo.gif` eklenince README'deki yer tutucu bağlantıya dönüşür ve
  `tests/test_readme.py` 5 MB sınırını kontrol eder.
- 2026-09-20 · **Ozan: plan küçültme (c) kapalı, ablation planı aynen duruyor.** Kota gerçeği
  Lite olmayan Flash'ta RPD 20 olduğu için **Dal B**: model seçimi ölçülerek yapılır, kural
  önce yazılır, Lite yalnızca birincil ölçütte açıkça öndeyse seçilir. Ayrıca: kota limitleri
  ölçülerek doğrulanır, model seçimden sonra kilitlenir, dondurma listesi genişler (gözlenen
  RPD dahil), 15 günü aşan süre tahmininde DUR-VE-SÖYLE, results.md'ye kota bölümü eklenir.
- 2026-09-20 · **Geçici karar: Lite olmayan model aday değil, referans.** Kuralın "Lite'ı ancak
  Lite olmayanı birincil ölçütte açıkça geçerse seç" maddesi, karşılaştırılabilir iki modeli
  varsayıyor. RPD 20 ile `gemini-3.8-flash` planı 167 günde bitirir; Ozan'ın 15 gün sınırıyla
  kazansa bile kullanılamaz. Bu yüzden kendi günlük kotasından 2 soru cevapladı ve results.md'de
  referans satırı olarak duruyor (n=2'lik doğruluk karşılaştırılabilir değil, rapor bunu yazıyor).
  Alternatif: Lite olmayanı 5-6 günde tam dev setinde koşturmak — projeyi 6 gün bekletirdi ve
  sonucu değiştiremezdi (yine kullanılamazdı).
- 2026-09-20 · **`observed_rpd` sunucunun bildirdiği değer, o günün sayacı değil** (Ozan'ın
  maddesi "gerçekleşen istek sayısını yaz" diyordu) · 429 gövdesindeki `QuotaFailure` gerçek
  limiti veriyor; guard'ın kendi sayacı guard dışından giden isteklerle (ham script, yoklama)
  eksik kalabilir, yani günü olduğundan küçük gösterirdi. Sunucu değeri yoksa gün sayacına
  düşülüyor (testli).
- 2026-09-19 · **Ozan'ın Faz 5 kontrol noktası kararları:**
  - **Q-D25-1: REST onaylandı**, üç korumayla (API sürümü sabit ve results.md'de; beklenmeyen şema
    = açık hata; ilk ham istek/cevap PROGRESS'te) + rol yedeği ("user" → 400'de "function" → "tool").
    "user" ilk denemede çalıştı.
  - **Q-D25-2: üç kırpma da pilottan önce** (title'lar, sayısal sinyal alanları, query yankısı) →
    v2, iterasyon sayılmaz; iki ölçüm de tutulur; `affected_reports` ve sahiplik yoluna dokunulmaz.
  - **Q-F5-1:** doğal ayrım ifadesi; tek ID'de `contains_all`; `min_mentioned_count` puanlanmaz ama
    ayrı sütunda görünür.
  - **Q-F5-2:** 11 tablo onaylandı; üç broadcast sorusu farklı departman kümeleri; hiçbir broadcast
    gold'u 7 başkanın tamamı değil (testli); EMP-001 en fazla bir broadcast gold'unda (aşağıda
    çatışma); results.md'de "örneklem küçük hub'lara kayık, bireysel doğruluk ölçülmüyor".
  - **Q-F5-3:** test null_formula 3 → 2, dev'e 1 null_formula; L6 test 15'te kalır, boşalan yer
    never_done'a; veri yeniden üretilmez; §9.2 güncellenir.
  - **Q-F5-4:** 2–15 sınırı onaylandı; elenen adaylar ve katman/derinlik dağılımı kaydedilir; L3 sığ
    düğümlere kayıyorsa results.md'ye sınırlama.
  - Teşhis puanları, trivial baseline'lar ve ön kayıt (yukarıda Tamamlananlar'da).
- 2026-09-19 · **Q-F5-2 çatışması — geçici karar: farklı kümeler kazanır, EMP-001 iki gold'da.**
  Seed 42'de başkanların tamamını içermeyen 11 hub tablonun yalnızca **3 farklı başkan kümesi**
  var ve bunların **2'si EMP-001'i içeriyor**. Üç soru farklı küme isterse EMP-001 en az iki
  gold'da olur (`question_sets.fewest_coo_broadcasts` = 2; test bunu veriden hesaplıyor).
  Farklı kümeleri seçtim: aynı ezber cevap iki soruya uymasın. EMP-001 sayısı bu kısıtta
  mümkün olan en düşük değer. Test kümeleri: {001,005,031,041,053,057}, {001,005,031,057},
  {005,032,053} · Alternatif: iki soruyu aynı kümeden sormak (EMP-001 bir kez, ama bir cevap iki
  soruya uyar) veya veri yeniden üretmek (Ozan "üretme" dedi).
- 2026-09-19 · **Broadcast gold'unda `forbidden_ids` = etkilenmeyen departmanların başkanları**
  (geçici karar) · "Herkese haber ver" cevabı (7 başkan) `contains_all`'ı geçerdi; yasaklı başkan
  onu düşürüyor (all_heads baseline 0,00). Alternatif: `set_f1` (bir fazla başkan da puan kırardı,
  D24'ün `contains_all` kararına aykırı).
- 2026-09-19 · **Q-F5-4 elenen adaylar (L3, 2–15 sınırı):** metric_upstream 37 aday → 20 kaldı, 17
  çok büyük (tam lineage medyanı kalan 15 / elenen 19) · report_upstream 180 kaldı; derinlik 2 hepsi
  için, derinlik 3 80 için mümkün · staging_downstream 30 aday → 19 kaldı, 11 çok büyük (medyan 26 /
  32). Seçilen derinlikler çoğunlukla 2 → L3 sığ hedeflere kayıyor; results.md "Threats to
  validity"de `_test_set_notes` bunu set dosyasından sayarak yazıyor.
- 2026-09-19 · **`llm_error` cevapları yazılmıyor ve puanlanmıyor** (runner) · Sağlayıcı hatasıyla
  biten bir cevap boş cevap gibi puanlansaydı L6'da bedava doğru abstain sayılırdı; yeniden
  koşumda tekrar denenir. Arka arkaya 3 → `ProviderDown`, koşum temiz durur (çıkış kodu 1).
- 2026-09-19 · **503 UNAVAILABLE = geçici kota** (`RateLimited`, aynı geri çekilme) · Canlı smoke'ta
  "model overloaded" geldi; hata saymak cevabı düşürürdü.
- 2026-09-19 · **D25 (Ozan): sıfır para.** Gemini Flash, Google AI Studio ücretsiz katman.
  Fiyatlar 0, `EVAL_BUDGET_USD=0`. Para koruması yerine kota koruması; devam ettirilebilir
  koşum; plan 665 (tekrar yalnızca A0'da); demo serbest metni varsayılan kapalı · Gerekçe: bütçe
  sıfır; kısıt altında ölçüm yapılıp kaydediliyor · Bedel: ablation'lar tek koşum, küçük etkiler
  ayırt edilemez. Spec güncellendi: §0.3 H1–H3, §8.1, §8.6, §9.8, §9.9, §9.10 (kota koruması),
  §9.11, §10.2, §11.2, §16, Ek C.2, Ek C.4, §15 D25.
- 2026-09-19 · **Geçici kararlar (D25 uygulaması, spec'te yok):**
  - **SDK yerine REST (SPEC-DEVIATION):** `generateContent` httpx ile çağrılıyor · 429'un bekleme
    ipucu (`Retry-After` veya gövdedeki `RetryInfo.retryDelay`) doğrudan okunabiliyor. Yeni bağımlılık
    yok (httpx zaten sabit), dosya indirme yok · Alternatif: google-genai SDK (resmi, ama hata
    ayrıntılarını sarıyor ve yeni bir pin gerektiriyor).
  - **Interactions API yerine `generateContent`:** Doküman Interactions'ı yeni projeler için
    öneriyor, `generateContent`'i "legacy ama tam destekli" diyor. Bizim döngü geçmişi kendisi
    tutuyor ve önbellek anahtarı tam mesajlar; durumsuz `generateContent` buna birebir uyuyor.
  - **Anahtar `x-goog-api-key` başlığında**, URL'de değil · URL'deki anahtar hata mesajı ve log
    yoluyla sızabilirdi.
  - **Model turu aynen geri gönderiliyor** (`LLMResponse.provider_state`) · Doküman "thought
    bloklarını alındığı gibi geri gönder" diyor. İmzalı turlar kaybolmasın.
  - **`functionResponse` `role: "user"` turunda**, ardışık tool sonuçları ve döngünün sonraki
    talimatı tek turda birleşiyor · **Dokümanda doğrulayamadım** (sayfa Interactions'a taşınmış).
    İlk canlı çağrıda doğrulanacak.
  - Model ID'siz fonksiyon çağrısı döndürürse döngü yerel bir ID (`local-N`) veriyor ve cevapta
    ID'yi göndermiyor.
  - Token sayımı: input = `promptTokenCount` + `toolUsePromptTokenCount`, output =
    `candidatesTokenCount` + `thoughtsTokenCount`.
  - Tool sonucu Gemini'ye `payload_json`'un ayrıştırılmış nesnesi olarak gidiyor
    (`functionResponse.response`); içerik birebir aynı.
  - Throttle penceresi 60 sn + 1 sn pay; bir isteğin input'u önceden karakter/4 ile tahmin ediliyor;
    pencere boşsa istek her zaman geçiyor. Jitter aralığı gecikmenin 0,5–1,5 katı; 5 başarısız
    yeniden denemeden sonra `QuotaExhausted`.
  - Sonuç dosyası adında SHA yok (`<set>_<config>_r<repeat>.jsonl`); SHA her satırda · Günlerce
    süren bir koşum tek dosyada kalsın. Rapor meta satırı kullanılan SHA'ları listeliyor.
  - `--no-resume` dolu bir dosyaya dokunmayı reddediyor (sessizce üzerine yazmıyor).
  - Tek kota sarmalayıcı bütün tekrarlar boyunca yaşıyor (dakika penceresi tekrarlar arasında
    sıfırlanmasın).
  - `--env-file` bayrağı: testler gerçek `.env`'i asla okumaz (canlı çağrı riski yok).
  - Rapor: `$/q` yerine token/soru; ablation hücreleri A0'ın aynı sütundaki tekrar std'si içindeyse
    "≈". A0'da iki tekrardan azı varsa işaret yok.
  - Demo (Faz 8) kararı spec §10.2'ye yazıldı; uygulama Faz 8'de. Demo serbest metni de
    `QuotaGuardedLLM` ile sarılacak, çünkü kota proje başına paylaşılıyor.
- 2026-09-19 · **Geçici kararlar (Faz 5, spec'te yok):**
  - Dev alt dağılımları: L1 = exact 1 · paraphrase 2 · disambiguation 1; L3 = metrik 1 · rapor 2 ·
    staging 1; L6 = maaş 1 · 2027 bütçe 1 · yakın-ıska 2 · hiç yapılmamış 1 · gelecek 1; MX = metrik 1 ·
    deprecated 1 · talep 2 (Q-F5-3).
  - Boş formüllü metrik yalnızca 3 tane; üçü de test setine gidiyor, dev setinde boş formül sorusu yok
    (örtüşmesizlik kuralı).
  - L1 exact test: 2 rapor ID + 1 rapor adı + 1 tablo adı + 1 metrik kısaltması.
  - L3 gold büyüklüğü 2–15 ID; derinlik buna göre seçiliyor (rapor 2/3, staging 2/3/4, metrik 3) ·
    D24 mantığı: 15'ten fazla ID lineage'ı değil kopyalamayı ölçer.
  - L5 broadcast hedefleri, etkilenen departmanların tüm departmanların alt kümesi olduğu tablolar
    (33 broadcast tablonun 22'sinde gold 7 başkanın tamamı; o sorularda "herkese duyur" tahmini
    okumadan doğru olurdu) (Q-F5-2).
  - L5 individual katman karışımı: test 4 mart + 3 intermediate/staging, dev 1 + 1.
  - Birincil hedef tekliği hem setler arasında hem set içinde (aynı rapor iki kategoride sorulmuyor).
    Seçim sırası kıt hedefler önce: L2, L6, L1, MX, L3, L5, L4.
  - MX metrik zincirinde "kaynak tablolar" = metriğin doğrudan kaynakları (derinlik 1); kaynakların
    hepsi individual modda (D24). MX talep zinciri yalnızca tek bir aktif sonuç raporu olan kümelerden.
  - L6 "hiç yapılmamış" konuları `reserved_near_miss.json`'daki 8 konudan (veri bütünlüğü testiyle
    korunuyor); yakın-ıska isimleri retrieval setinde kullanılmamış isimlerden, her parça bir kez.
  - Soru ID'leri: test `L2-007`, dev `dev-L2-01`.
  - Gold `current_contact_for_asset` birden çok varlık alabiliyor (`asset_ids`); MX metrik zinciri için.
  - Pilot = spend_log'daki en son dev A0 koşusu; test koşusunun maliyet tahmini ondan. Pilot yokken
    test koşusu reddediliyor. Dev koşuları ve kuru koşumlar `eval/results/scratch/`'e yazılıyor.
  - `--llm fake` her soruya abstain eden bir model; spend_log'a yazmıyor.
  - Rapor: ± std en az 2 tekrar ister (1 tekrarda "(1 repeat)"); CI soruları yeniden örnekliyor
    (1.000, seed 0); tool hata oranına BUDGET sayılmıyor (durma nedenlerinde görünüyor); uydurma ID
    oranı = `stripped_ids` dolu cevap / tüm cevaplar.
  - Ortak sızıntı kuralları `eval/set_rules.py`'ye taşındı (refactor; retrieval seti birebir aynı
    üretiliyor).
- 2026-09-19 · **Geçici kararlar (Faz 4, spec'te yok):**
  - `PROMPT_VERSION` `config.py`'de; `prompts.py` onu kullanıyor · `AgentConfig` config'te,
    agent paketini import etmesin (katman döngüsü olmasın).
  - Tam prompt'un sha256'sı `PROMPT_HASHES[PROMPT_VERSION]`'a sabit · Metin değişirse test
    kırılır, sürüm artırmak zorunlu olur (§8.4 kuralını kodla uygular).
  - A5'te prompt `impact_analysis` adını hiç geçirmiyor (Prefer ve broadcast satırları düşüyor) ·
    Model olmayan bir tool'a yönlendirilmesin; A3'teki spec notunun aynı mantığı.
  - Grounding cevap **metnini** de tarıyor; yalnızca metinde geçen görülmemiş ID de
    `[unverified]` olur ve `stripped_ids`'e girer · D12: uydurma ID kullanıcıya ulaşmamalı.
    Spec yalnızca listeleri sayıyordu; uydurma ID oranı bu yüzden spec'in lafzından daha sıkı.
  - Abstain cevabının `answer_ids`'inde EMP olması kodla engellenmiyor · Engellenseydi puanlamadaki
    "abstain ∧ EMP yok" koşulu hep doğru çıkar, model hatası ölçülemezdi.
  - `parse_final` kod bloğunu ve JSON'un etrafındaki cümleyi tolere ediyor; eksik alan veya yanlış
    tip okunamaz sayılıyor → onarım turu.
  - Agent, config'i registry'den alıyor (`registry.config`) · Prompt, tool listesi ve sınırlar tek
    kaynaktan gelsin.
  - Onarım ve zorlanmış final turları `max_llm_turns`'e sayılmıyor · En kötü durumda soru başına
    11 başarılı LLM çağrısı (10 tur + 1 zorlanmış final), her biri en fazla 3 deneme.
  - Başarısız LLM denemeleri iz'e yalnızca istisna tipiyle yazılıyor (mesaj sağlayıcı ayrıntısı
    taşıyabilir); geri çekilme 1 sn, 2 sn.
  - `AgentResult.tool_calls` yalnızca çalışan çağrıları sayar; `BUDGET` alanlar iz'de adım olarak var.
- 2026-09-18 · **D24 (Ozan, Q-F3-1):** `impact_analysis` ölçeğe göre biçim değiştirir (≤ 20 kişi
  bireysel liste; > 20 ilk 10 + departman kırılımı; impact için çıktı sınırı 6.000) · Bireysel
  bildirim ölçekte anlamsızlaşıyor; 72 ID'lik bir liste L5'i kopyalama testine çevirirdi ·
  Reddedilen: (a) notify tam + sınır aşımı, (b) notify'ı kesmek, (c) aşımda yalnızca ID listesi ·
  Bedel: broadcast cevaplar bireysel doğrulukta ölçülmüyor (gold = departman başkanları).
  Önceki geçici kararım ("notify kazanır, sınır aşılır") bununla geçersiz.
- 2026-09-18 · **Geçici karar (D24 ayrıntıları, spec'te yok):**
  - `notify_rollup` sırası: `people_count` azalan, sonra departman adı.
  - `NotifyRollup.report_count`: o departmandaki kişilere yönlenen etkilenen **active** raporlar.
    Deprecated raporların sahibi bildirilmediği için (D10) bu sayıda yok.
  - `affected_report_count`: `affected_reports` listesiyle aynı küme (active + deprecated).
  - Ozan'ın "her tabloda rollup `people_count` toplamı = `notify_total_count`" maddesi broadcast
    tablolarda test ediliyor. Individual modda rollup tanım gereği boş; orada tamlık
    `notify` listesinin gold ile birebir eşitliğiyle test ediliyor.
  - L5'teki 7 individual + 3 broadcast soruda katman karışımı korunacak (Faz 5 seçimi
    `impact_fanout.json`'dan).
  - `results.md`'deki A5 yorumu ("broadcast sorularında tool bütçesinin tükenmesi ablation'ın
    ölçtüğü şey") A5 sonuçları gelince `eval/report.py`'ye yazılacak (Faz 7/8).
- 2026-09-18 · Bağımsız impact gold'u (`eval/gold.py:current_contact`, `impact_notify`) Faz 5
  yerine şimdi yazıldı · Ozan'ın istediği "bağımsız pandas hesabı" testi bunu gerektiriyordu;
  Faz 5 yalnızca gold_spec bağlantısını ekleyecek. Önce mini fixture'da elle hesaplanan
  değerlerle test edildi. Tool ile gold, 80 tabloda ve 17 seed'de birebir aynı.
- 2026-09-18 · `eval/runinfo.py:git_sha()` benchmark ve fan-out script'lerinde ortak (refactor).
- 2026-09-18 · `AgentConfig` şimdi `config.py`'de; `prompt_version` Faz 4'te prompt ile gelecek ·
  Registry ona Faz 3'te ihtiyaç duyuyor. Spec'te olmayan ek: `tools_enabled` bilinmeyen tool
  adını reddediyor (bir ablation'da yazım hatası bir tool'u sessizce kapatmasın).
- 2026-09-18 · Registry: hata çıktılarından kayıt ID'si toplanmıyor · "RPT-0999 does not exist"
  grounding'e görülmüş ID gibi girmesin · Alternatif: regex'i her çıktıya uygulamak (spec'in lafzı).
- 2026-09-18 · Registry: beklenmeyen istisna → `INTERNAL` + genel mesaj, ayrıntı `logging` ile
  loglanıyor · Bir tool hatası agent koşusunu bitirmesin ve kullanıcıya iç ayrıntı sızmasın.
- 2026-09-18 · `payload_json()` = LLM'e giden tek serileştirme (kompakt, UTF-8), `model_dump_json()`
  ile birebir aynı (test var) · 4.000 sınırı tool'da hangi metin üzerinde ölçüldüyse LLM o metni
  görsün; varsayılan `json.dumps` boşluk ekliyor (ör. 3.9k → 4.3k). Faz 4 döngüsü bunu kullanmalı.
- 2026-09-18 · A4'te (`show_match_quality=False`) `signal` her iki arama tool'unun çıktısından
  (search_assets **ve** find_similar_past_work) çıkıyor ve tool açıklamalarındaki sinyal cümlesi
  de düşüyor · Ablation'da sinyal hiçbir yoldan modele ulaşmasın.
- 2026-09-18 · Tool açıklamaları registry'de elle yazıldı (İngilizce, 2–3 cümle) · Parametre
  şemaları `model_json_schema()` ile üretiliyor (§7.1); açıklamalar dev setinde değişebilir
  (prompt iterasyonu sayılır, en fazla 3).
- 2026-09-18 · **Ozan'ın Faz 2 kararları (nihai):** (1) parafraz havuzu düzeltilsin (eksik builder
  doğrulaması); (2) sinyal tanımı değişsin, mutlak ve göreli (z) taransın, iyi olan sabitlensin;
  (3) hibritte ID yönlendirmesi yok, RRF özelliği olarak yazılsın; (4) retrieval setinin hedefleri
  dev/test L1 sorularında kullanılmasın (L2/L3/L5 serbest) — Faz 5'te uygulanacak; (5) I07: S1/S2
  ≥1, C ≥2 rapor, I18 ≤ %18; (6) D için başlık metrik pair_coverage@5, doğru üyeyi seçmek agent'ın
  işi (L1); (7) sızıntı düzeldikten sonra tek A/B: MiniLM vs bge-small; (8) bağlayıcılar kullanılmıyor.
  Çalışma biçimi: bkz. `CLAUDE.md` "Decision authority".
- 2026-09-18 · Açıklama örtüşmesi ölçüsü: sorgunun içerik kelimelerinin (spec stop-word'leri, açık
  İngilizce işlev kelimesi listesi ve parafraz şablonunun sabit kelimeleri çıkarıldıktan sonra)
  hedefin açıklama+etiketlerinde geçen payı · Şablon kelimeleri her sorguda aynı olduğu için hedefi
  işaret edemez; paydanın sorgu tarafında olması en sert seçenek · Not: önceki raporda geçen "9/15
  sorgu ≥2 ortak kelime" daha kaba bir ölçüydü (işlev kelimeleri dahil); resmi ölçüyle v1: ortalama
  %23, 6/15 sınır üstü.
- 2026-09-18 · τ_z ızgarası 0,5–6,0 (adım 0,25) veriye bakmadan sabitlendi; sinyal varyantı eşitlikte
  mutlakta kalır · Model A/B kuralı koşumlardan önce koda yazıldı (7665139, `choose_model`).
- 2026-09-18 · v1 karşılaştırması için eski üretici (7cdffa2) bir git worktree'de çalıştırılıp veri
  geçici klasöre üretildi; v1 seti bu veride yeniden puanlandı · Eski ve yeni set aynı kod ve modelle
  karşılaştırılabilsin. Orijinal v1 JSON'u (`retrieval_bench_v1.json`) değiştirilmeden saklandı.
- 2026-09-18 · `tests/test_config_matches_bench.py`: config'teki model ve sinyal, commit edilmiş
  benchmark sonuçlarından kuralla seçilenle aynı olmak zorunda · config sonuçlardan kaymasın.
- 2026-09-18 · bge-small sorgularına talimat öneki eklenmedi · İki model aynı boru hattında
  karşılaştırılsın; v1.5 model kartı önekin şart olmadığını söylüyor.
- 2026-09-18 · **Protokol hatası (2.):** gcommit yardımcısında `git add` başarısız olunca yalnızca
  dosya taşımasını içeren bir commit oluştu; yerelde geri alınıp (push edilmemişti) doğru içerikle
  7665139 olarak yeniden atıldı. Yardımcı artık `git add` başarısız olursa duruyor.
- 2026-09-18 · BM25 aday ölçütü "skor > 0" değil "en az bir ortak token" · Okapi idf yarıdan
  fazla belgede geçen terimlerde negatif/tabanda (ör. her rapor ID'sindeki `rpt`); bir test yakaladı.
- 2026-09-18 · MatchSignal her modda aynı hesaplanıyor (bm25 modunda da dense kosinüs) · A1/A2
  ablation'ları yalnızca sıralamayı değiştirsin, abstain kanıtını değil · Alternatif: bm25 modunda
  sinyal yalnızca exact_match (A2'yi abstain etkisiyle karıştırırdı).
- 2026-09-18 · exact_match: sorguda maskelenmiş korpustaki bir kaydın ID'si ya da tam normalize
  ismi; metrik alias'larından yalnızca kısaltma ("AOV", "GM%") veya çok kelimeli olanlar sayılıyor ·
  "units", "turns" gibi gündelik kelimeler her sorguyu strong yapardı.
- 2026-09-18 · `retrieval/corpus.py` eklendi (belge metinleri §5.2) · `hybrid.py` generic kalsın.
- 2026-09-18 · Mini fixture (`tests/fixtures/mini/`) Faz 3 ihtiyaçlarıyla birlikte şimdi tasarlandı
  (tüm devir durumları, döngü, çıkmaz sokak, deprecated rapor, etki analizi durumları) · Faz 3'te
  tekrar iş olmasın. 14 çalışan (spec ≈12).
- 2026-09-18 · Retrieval seti: E = 5 tablo adı + 5 metrik kısaltması (rapor etiketi olmayanlar,
  tek hedef olsun) + 5 rapor ID; P hedefleri "none" nitelendiricisiz, gürültü/belirsiz olmayan
  aktif raporlar, konu başına bir sorgu; D = 8 deprecated + 7 yakın-kopya; N = rezerve parçalardan
  var olan hiçbir ismi içermeyen isimler. Set bir testte yeniden üretilip commit edilenle karşılaştırılıyor.
- 2026-09-18 · τ seçimi: macro-F1 (strong vs weak); platoda orta (çiftse alt orta) · 45 pozitife
  karşı 15 negatifte tek sınıf F1'i düşük τ'yu ödüllendirirdi.
- 2026-09-18 · Benchmark JSON'u git SHA'sını kaydeder; yalnızca izlenen dosya değişiklikleri
  "-dirty" sayılır · Sonuçlar temiz commit'ten (1d37885) yeniden üretildi, sonuçlar aynı.
- 2026-09-18 · **Protokol hatası:** tokenizer ve BM25 commit'leri (fc85f1b, 8ba3298) başarısız bir
  kapıyla (ruff SIM905/SIM300) girdi; komut zinciri grep'in başarısına bakıyordu. fc4397a ile
  düzeltildi; commit artık doğrudan `check_all.py` çıkış koduna bağlı bir yardımcıyla atılıyor.
- 2026-09-18 · **Ozan onayları (Faz 1 kontrol noktası):** Python 3.13 sapması onaylandı (CI,
  Dockerfile, README aynı sürümü söyler); `/data/`, yalnız `generate.py` muafiyeti ve torch CPU
  index sapmaları onaylandı; E501 kapatma kabul edildi, uyarıyla: kapıyı geçmek için kural
  gevşetme refleksi testlerde yasak (CLAUDE.md'ye işlendi); LICENSE adı doğru; H5, H6 ve remote
  repoyu Ozan hallediyor, o zamana kadar push yok. Store testlerinde kırmızı koşumu atlamıştım;
  bundan sonra her testin önce başarısız olduğu görülüyor (CLAUDE.md'ye işlendi).
- 2026-09-18 · **Ayrılmış sahip oranı:** İlk gerekçem ("spesifikasyon dayatıyor") yanlıştı;
  oran benim düzgün sahip dağılımımdan geliyordu. Artık aktif raporların sahibi bugün şirkette
  olan biri; tek istisna zincir başlarının I07 gereği sahip olduğu **tam iki** rapor. Deprecated
  raporların sahibi ayrılmış biri olabilir (gerçekçi, orana girmiyor).
- 2026-09-18 · Tablo ve metrik sahiplerinde de ayrılmış oranı %17,5'e (80'de 14, 40'ta 7) tam
  sayıyla sabitlendi · Ozan'ın gerekçesinin (L2, L5 ve A3) doğrudan uzantısı: L5 bildirim listesi
  metrik sahiplerini, L2/MX tablo sahiplerini içeriyor · Alternatif: yalnızca raporlara uygulamak.
- 2026-09-18 · Rapor isimleri: her konuya 2 alternatif isim kökü eklendi (aynı konuya farklı ekip
  isimleri) + üretimde `_NameRegistry` her yeni ismi mevcut isimlerle karşılaştırıp J > 0,6 ise
  reddediyor; türetilmiş isimler (yakın-kopya, replacement) yalnızca kendi kökenlerine benzeyebilir.
  Jaccard, I14 ile aynı token tanımını kullanıyor (küçük harf, `[a-z0-9]+`, stopword atılmıyor).
- 2026-09-18 · Talep başlıkları: küme içi benzerlik tasarım gereği serbest (aynı konunun
  parafrazları), kümeler arası J > 0,6 üretimde reddediliyor.
- 2026-09-18 · "Regional"/"Area Managers" yakın-kopya varyantı, konunun **herhangi** bir raporu
  "by Region" ise kullanılmıyor · Jaccard 0,5 ile geçen ama anlamca aynı olan çift bulundu.
- 2026-09-18 · Şablonlar "deste" ile dağıtılıyor (karışık turlar, her şablon eşit sayıda);
  rapor açıklama şablonu 6 → 10, talep başlık kalıbı 8 → 12, talep açıklama kalıbı 5 → 10 ·
  I20 eşiği: ilk kelime payı ≤ %15 (ilk kelime, iki kelimeden daha sert bir ölçü).
- 2026-09-18 · Repo yerelde `git init -b main` ile başlatıldı; master doküman sohbetten
  `docs/plan/` içine kaydedildi · Dizin boştu, önkoşul (GitHub klonu) yapılmamıştı ·
  Alternatif: Ozan'ın repoyu oluşturmasını beklemek (işi bloklardı). GitHub repo'su
  README/LICENSE/.gitignore **olmadan boş** oluşturulup remote olarak eklenmeli.
- 2026-09-18 · LICENSE sahibi "Ozan Dokur" yazıldı · git kullanıcı adından çıkarım ·
  Yanlışsa düzeltilecek.
- 2026-09-18 · Yasaklı terim ve sır taraması "git'in commit edeceği" dosyaları tarar
  (`git ls-files --cached --others --exclude-standard`) · Yalnızca takip edilenleri taramak
  ilk commit'ten önce hiçbir şey yakalamazdı · Alternatif: yalnızca tracked (spec'in lafzı).
- 2026-09-18 · Yasaklı terim eşleşmesi büyük/küçük harf duyarsız **alt dize**; çıktı terimi
  değil terimin sıra numarasını basar · Kelime sınırı sızıntı riskini artırır; terimi
  basmamak logların terimi sızdırmasını engeller · Alternatif: kelime sınırlı eşleşme.
- 2026-09-18 · Sır taraması `sk-`/`hf_` için önünde harf/rakam olmamasını ve minimum uzunluk
  ister · "risk-free", "task-list" gibi kelimeler yanlış alarm vermesin · Ek kalıplar: GitHub,
  AWS, Google anahtarları, private key bloğu.
- 2026-09-18 · `.env.example` kuralı "adında KEY/TOKEN/SECRET/PASSWORD geçen değişkenler boş"
  olarak yorumlandı · Ek C.2 `EMBEDDING_MODEL` ve `DEMO_DAILY_LIMIT` için değer veriyor;
  "tüm değerler boş" kuralı bununla çelişirdi.
- 2026-09-18 · `eval/gold.py` import beyaz listesi: pandas, json, `metacompass.data.schema`
  + zararsız stdlib (`__future__`, collections, dataclasses, pathlib, typing) · BFS için
  deque gerekir · networkx ve diğer metacompass modülleri yasak kalır.
- 2026-09-18 · Mimari testine ek kurallar: FAISS/Neo4j import yasağı, src içinde relative
  import yasağı (katman kontrolünü atlatmasın), her src modülünde docstring (§13.1 kural 10).
- 2026-09-18 · pandas 3.0 / numpy 2.5 ile geliştiriliyor; pyproject alt sınırları buna göre
  (`pandas>=3.0`, `numpy>=2.0`) · pandas 3'te varsayılan string dtype ve Copy-on-Write var.
- 2026-09-18 · Ruff E501 (satır uzunluğu) kapalı · Satır düzenini `ruff format` zorluyor;
  formatter uzun string'leri bölmediği için E501 yalnızca metin/tablo satırlarını işaretliyordu.
- 2026-09-18 · Testler veriyi oturum başına geçici klasöre **kendileri üretir** (`conftest.py`)
  · Bayat `data/` ile yanlış yeşil riski yok · CI yine de `data/` üretir (sonraki fazlar için).
  `METACOMPASS_TEST_SEED` ile invariant'lar başka seed'lerde de koşturulabilir.
- 2026-09-18 · Aşama başına RNG (`random.Random(f"{seed}:{stage}")`) · Bir vocab değişikliği
  tüm tabloları yeniden karıştırmasın · Alternatif: tek RNG (spec'in lafzı; daha kırılgan).
- 2026-09-18 · Devir yapıları departmanlara elle dağıtıldı (en çok Sales), yapılar yalnızca
  ekip üyelerinden kurulur; başkan/lider hep aktif · Yöneticiye düşen yollar (S2, C2b) her zaman
  aktif birine ulaşır. Test split'teki C2 zincirleri iki varyantı da (succ→succ, succ→manager) içerir.
- 2026-09-18 · Employee ID'leri işe giriş sırasına göre (COO her zaman EMP-001); rapor ID'leri
  oluşturma sırasına göre; tablo ID'leri katman sırasına göre (int→int kuralı için gerekli).
- 2026-09-18 · Rapor isimleri = (konu, nitelendirici) çifti + opsiyonel biçim kelimesi; her çift
  bir kez kullanılır · İki rapor yalnızca "Dashboard/Report" kelimesiyle ayrışmasın.
- 2026-09-18 · Gürültü çiftleri (15 deprecated + 20 yakın-kopya) konu başına en fazla bir tane ·
  Katalog geneline yayılsın. Belirsiz açıklamalar (N4) gürültü çiftlerine hiç verilmez ve rapor
  ismindeki hiçbir kelimeyi içermez (seed 2'de yakalanan hata üzerine eklendi).
- 2026-09-18 · Spec'te olmayan ama ima edilen gerçekçilik kuralları testlere eklendi (X-testleri):
  rapor oluşturma tarihi ≥ sahibin başlangıcı; talep sahibi/atanan talep tarihinde çalışıyor;
  ayrılan çalışanın yöneticisi aktif; yapılan taleplerin ~%75'inde sonuç raporu (0,70–0,80).
- 2026-09-18 · `_meta.json`'a spec örneğinde olmayan alanlar eklendi: `near_duplicate_variants`,
  `report_subjects`, `report_qualifiers`, `vague_description_reports` · Eval builder'ın parafraz
  ve D-sorgusu üretmesi için gerekli. 7 tablonun şeması değişmedi (§2.3 kapsam değişikliği değil).
- ~~2026-09-18 · Ayrılmış sahipli rapor oranı ~%40 kabul edildi~~ · Geçersiz: gerekçe yanlıştı
  (spec dayatmıyordu); önce taban %21,3'e, sonra I07 gevşetmesiyle %13,6'ya indirildi.

## Spec sapmaları
- **Sağlayıcı istemcisi SDK değil REST (§8.1, Ek C.3) — ONAYLANDI 2026-09-19 (Q-D25-1):** Gerekçe
  yukarıda. Kodda `SPEC-DEVIATION` yorumu var (`agent/llm.py:GeminiClient`). API `v1beta` sabit.
- **Python sürümü (§11.1, §12.5) — ONAYLANDI 2026-09-18:** Spec CI/Docker için 3.11 diyor.
  `pip freeze` ile sabitlenen numpy 2.5.3 ve scipy 1.18.1 Python ≥ 3.12 istiyor, yani 3.11'de
  kurulamaz. Karar: yerel = CI = Docker = Python 3.13; `requires-python = ">=3.12"`, ruff hedefi
  py312; README ve CI 3.13 diyor, Dockerfile (Faz 8) `python:3.13-slim` kullanacak.
  Reddedilen alternatif: Python 3.11 + eski numpy/scipy sürümlerine sabitlemek (yerel ortamı da
  3.11'e düşürmek gerekirdi; iki ayrı yorumlayıcıyı eşzamanlı tutma maliyeti).
- **`.gitignore` `data/` (Ek C.1) — ONAYLANDI:** Kök dışındaki `src/metacompass/data/`
  klasörünü de yok sayardı. `/data/` (köke sabitli) kullanıldı.
- **`_meta.json` string yasağı (§12.2) — ONAYLANDI:** `src/**` içinde tamamen yasak olursa
  üretici dosyayı yazamaz. Yalnızca `src/metacompass/data/generate.py` (yazan) muaf.
- **Torch pini — ONAYLANDI:** `requirements.txt` başına `--extra-index-url https://download.pytorch.org/whl/cpu`
  eklendi; aksi halde `torch==…+cpu` pini Linux'ta PyPI'dan çözülemez.
- **Tek RNG kaynağı (§4.1):** Tek RNG yerine aşama başına türetilmiş `random.Random` örnekleri
  (hepsi aynı seed'den). Determinizm korunuyor (I17).

## Açık sorular (Ozan'ın cevabı bekleniyor)
- [ ] **Q-F8-3 — Ozan'ın elinde:** Streamlit Community Cloud'da Deploy (ayarlar gün sonu
  raporunda). URL gelince V8 (Streamlit Cloud'a uyarlanmış) koşulur ve README'ye eklenir.
- [x] **Q-F8-2 — kapandı 2026-09-22 (Ozan):** HF PRO yok; demo Streamlit Community Cloud'da,
  hafif demo profiliyle (serbest metin kapalıyken torch / sentence-transformers yüklenmez).
  HF deploy script'i PRO'su olan için kalıyor; README'de "isteğe bağlı: Docker".
- [x] **Q-V0-1 — kapandı 2026-09-22 (Ozan: önbellekten yeniden oynatma):** 158/158 birebir.
- [x] **Q-F8-1 — kapandı 2026-09-21:** Docker ve PyPI indirmesi onaylandı; V2, V3, V5 yapıldı.
- [x] **Q-QUOTA-1 — kapandı 2026-09-20 (Ozan):** plan küçültme kapalı; Dal B uygulandı.
- [x] **Q-ENV-1 — kapandı:** `.env` seçilen modele ve RPD 500'e güncellendi; guard gerçek
  limiti 429'dan öğreniyor.
- [ ] **Q-F5-2b — geçici karar:** üç farklı broadcast kümesi EMP-001'i iki gold'a koyuyor (kural
  "en fazla bir"); farklı kümeler seçildi. Gerekçe Kararlar'da. Başka tercih varsa set yeniden
  üretilir (veri değil).
- [ ] **Q-F5-2c — geçici karar:** broadcast gold'unda yasaklı ID = etkilenmeyen departman başkanları.
- [ ] **Q-QUOTA-1 — DUR-VE-SOR (kota = D25'in bütçesi; plan bu kotayla yürümüyor):**
  `gemini-3.7-flash`'ın ücretsiz katman günlük limiti **20 istek** (proje + model başına; 429
  gövdesinden okundu). Canlı smoke'a göre cevap başına 2–4 LLM çağrısı var (en kısa yol 2,6).
  | iş | cevap | çağrı (3–4/cevap) | 20/gün ile |
  |---|---|---|---|
  | dev pilotu | 30 | 90–120 | 5–6 gün |
  | 3 prompt iterasyonu | 90 | 270–360 | 14–18 gün |
  | test planı (A0×3 + A1–A5) | 665 | 2.000–2.660 | 100–133 gün |
  Seçenekler: (a) AI Studio'nun rate-limit sayfasında (aistudio.google.com/rate-limit) günlük
  limiti yüksek, Lite olmayan bir Flash modeli varsa ona geçmek (henüz hiçbir sonuç yok, ölçüm
  zarar görmez; anahtarda gemini-2.5-flash, 3.5/3.6/3.7/3.8-flash var) · (b) ücretli katman,
  D25'i geri alır: ~785 cevap × ~7,5k input + ~450 output token ≈ 5,9M in + 0,35M out;
  `gemini-3.7-flash` 31.12.2026'ya kadar $0,75 / $3,75 per 1M → **~$6** (belirsizlikle $5–10) ·
  (c) ücretsiz kalıp planı küçültmek (ör. A0 ×1 test + ablation'lar kategori alt kümelerinde);
  ölçümü zayıflatır, results.md'de sınırlama olarak yazılır. Öneri: önce (a) kontrol; yoksa (b).
- [ ] **Q-ENV-1 — bilgi:** `.env`'deki limitler (15/1.500/1M) gerçek değil; gözlenen RPD 20. Guard
  `.env`'deki değeri kullanıyor. Sunucunun 429'u yine de koşumu temiz durduruyor (günde bir boşa
  istek). Gerçek değerleri yazarsan guard 21. isteği hiç göndermez.
- [x] **Q-F5-1, Q-F5-2, Q-F5-3, Q-F5-4, Q-D25-1, Q-D25-2 — kapandı 2026-09-19** (Ozan; Kararlar'da).
- [x] **Q-D25-3 — kapandı:** `functionResponse` rolü `"user"` ilk canlı çağrıda doğrulandı.
- [x] **`.env`, H5 (forbidden_terms), H6 (remote)** — Ozan 2026-09-19'da hazırladı; kontroller
  Tamamlananlar'da.
- [x] **Q-F3-1 — kapandı 2026-09-18, Ozan (d) seçeneğini seçti → D24.** Aşağıdaki kayıt tarihçe
  olarak duruyor. (DUR-VE-SOR: bir test assertion'ını değiştirme ihtiyacı.) §7.7'de iki kural
  çelişiyor: "çıktı ≤ 4.000 karakter" ve "`notify` kırpılmaz". Seed 42, 80 tablo: 49 tablonun tam
  çıktısı > 4.000. Diğer listeler boşaltıldıktan sonra bile 23 tablo (11 staging, 9 intermediate,
  3 mart: dim_date, dim_dealer, fct_vehicle_sales) > 4.000, en büyüğü 12.252 karakter (72 kişi).
  Neden: 250 rapor, ~600 rapor kenarı (≥%90 mart) ve 82 aktif çalışan (spec sayıları) → hub
  tablolar 50–72 kişiye bildirim gerektiriyor. Kişi başı ~165 karakter, yani ~24 kişiden sonra
  sınır matematiksel olarak tutamaz. `test_impact_size_limit_never_cuts_the_notify_list`
  TBL-003 için hem `≤ 4000` hem `notify == full.notify` iddia ediyor; ikisi birlikte sağlanamaz.
  Seçenekler:
  (a) **notify kazanır** (geçici karar, uygulandı): test yalnızca `≤ 4000` satırını bırakır; yerine
  yeni property testi zaten var (başka her liste boşalmadan sınır aşılmıyor, notify tam) ·
  (b) **sınır kazanır**: notify kesilir + `notify_total` sayacı; L5'te hub tablolar için cevap
  eksik kalır, Faz 5'te L5 hedefleri notify'ı sığan tablolarla sınırlanmalı ·
  (c) aşımda notify yalnızca ID listesine düşer (~720 karakter): sınır tutar, ama §7.7 şeması
  değişir ve agent isim/gerekçe göremez.
  Öneri: (a). Test dosyasına dokunmadım; karar gelene kadar kapı kırmızı, commit yok.
- [x] Faz 2 soruları (sızıntı, τ, ID yönlendirmesi, retrieval/test örtüşmesi, I07 bandı) — Ozan
  2026-09-18'de karara bağladı, yukarıda "Kararlar"da.
- [x] H1–H3 — Ozan 2026-09-19'da karara bağladı (D25): Gemini Flash ücretsiz katman, fiyat 0, bütçe 0.

## Takıldığım yerler
- (yok)
