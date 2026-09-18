# PROGRESS

## Durum
Aktif faz: 2 · Son güncelleme: 2026-09-18 ·
Son kapı: Faz 1 geçti (2026-09-18; kontrol noktası düzeltmeleri uygulandı)

## Dondurulmuş değerler
PROMPT_VERSION: — · τ: — (placeholder 0.45) · Model: — · Data seed: 42

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

## Devam eden
- Görev: Faz 2 — `retrieval/tokenize.py` · Yaklaşım: §5.3 kurallarını tablo tabanlı testlere
  dök (girdi → beklenen token listesi), kırmızıyı gör, sonra regex tabanlı tokenizer yaz.

## Kararlar ve gerekçeleri
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
- 2026-09-18 · Ayrılmış sahipli rapor oranı ~%40 kabul edildi · Spec 120 kişiden 38'inin
  ayrılmasını istiyor; oranı yapay düşürmek yerine data card'da "Known limits" altında yazılı.

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
- [ ] **%15–20 ayrılmış sahip bandı I07 ile birlikte tutturulamıyor.** Zincir başı sayısı 22
  değil 25 (S1 12 + S2 6 + C2 3 + C3 2 + C4 2); I07 gereği 25 × 2 = 50 aktif rapor ayrılmış
  kişilere ait olmak zorunda → taban 50/235 = %21,3. Geçici karar: oran tam tabanda (başka hiçbir
  aktif raporun sahibi ayrılmış değil); I18 `share ≤ max(0,20, taban)` olarak yazıldı
  (SPEC-DEVIATION yorumu testte). %20'nin altına inmek istersen spesifikasyon değişikliği gerekir,
  ör. S1 başları için I07'yi ≥1 rapora indirmek (taban 38/235 = %16,2) — senin kararın.
- [ ] H1–H3 (LLM sağlayıcı/model, bütçe, fiyatlar) — Faz 4'ten önce gerekli.
- [ ] H5: `docs/plan/forbidden_terms.txt` (Ozan hazırlıyor); push'tan önce tarama tüm dosyalar
  ve commit geçmişi için tekrar koşulacak.
- [ ] H6: `.env` ve GitHub remote (Ozan hazırlıyor). O zamana kadar push yok.

## Takıldığım yerler
- (yok)
