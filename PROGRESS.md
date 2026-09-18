# PROGRESS

## Durum
Aktif faz: 4 · Son güncelleme: 2026-09-18 · Son kapı: Faz 3 geçti (2026-09-18, Q-F3-1 → D24)

## Dondurulmuş değerler
PROMPT_VERSION: — · Embedding: BAAI/bge-small-en-v1.5 · Sinyal: z ≥ 4.25 (τ_z; mutlak τ = 0.70
yedek) · LLM: — · Data seed: 42 · Hepsi test koşumundan önce dondurulacak.

## Harcama
Kümülatif: $0.00 / $— (H2 bekleniyor) · Son koşum: —

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

## Devam eden
- Görev: Faz 4 — LLM istemcisi ve agent döngüsü · Yaklaşım: §8 sırasıyla llm → answer → prompts
  → loop, hepsi test önce ve FakeLLM ile ağsız. `.env` yok (H1–H3 boş) → ProviderClient ve live
  smoke atlanır, Ozan'a bildirilir.

## Kararlar ve gerekçeleri
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
- [ ] H1–H3 (LLM sağlayıcı/model, bütçe, fiyatlar) — Faz 4'ün canlı adımından önce gerekli.
- [ ] H5: `docs/plan/forbidden_terms.txt` (Ozan hazırlıyor); push'tan önce tarama tüm dosyalar
  ve commit geçmişi için tekrar koşulacak.
- [ ] H6: `.env` ve GitHub remote (Ozan hazırlıyor). O zamana kadar push yok.

## Takıldığım yerler
- (yok)
