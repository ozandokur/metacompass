# PROGRESS

## Durum
Aktif faz: 0 · Son güncelleme: 2026-09-18 · Son kapı: —

## Dondurulmuş değerler
PROMPT_VERSION: — · τ: — (placeholder 0.45) · Model: — · Data seed: 42

## Harcama
Kümülatif: $0.00 / $— (H2 bekleniyor) · Son koşum: —

## Tamamlananlar
- (henüz yok)

## Devam eden
- Görev: Faz 0 — iskelet, araçlar, kapı script'leri · Yaklaşım: pyproject + src düzeni,
  kapı script'leri (ruff, pytest+cov, yasaklı terim, sır taraması) test-önce yazıldı;
  requirements pip freeze ile sabitlendi, runtime/dev ayrımı pip dry-run raporundan çıkarıldı.

## Kararlar ve gerekçeleri
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
  (`pandas>=3.0`, `numpy>=2.0`) · pandas 3'te varsayılan string dtype ve Copy-on-Write var;
  kod buna göre yazılacak.

## Spec sapmaları
- **Python sürümü (§11.1, §12.5):** Spec CI/Docker için 3.11 diyor. `pip freeze` ile
  sabitlenen numpy 2.5.3 ve scipy 1.18.1 Python ≥ 3.12 istiyor, yani 3.11'de kurulamaz.
  Geçici karar: yerel = CI = Docker = Python 3.13; `requires-python = ">=3.12"`, ruff
  hedefi py312. Alternatif: 3.11 için numpy/scipy'yi eski sürümlere sabitlemek (yerel ortamı
  da düşürmek gerekir).
- **`.gitignore` `data/` (Ek C.1):** Kök dışındaki `src/metacompass/data/` klasörünü de
  yok sayardı. `/data/` (köke sabitli) kullanıldı.
- **`_meta.json` string yasağı (§12.2):** `src/**` içinde tamamen yasak olursa üretici dosyayı
  yazamaz. Yalnızca `src/metacompass/data/generate.py` (yazan) muaf; okuyucular yasaklı.
- **Torch pini:** `requirements.txt` başına `--extra-index-url https://download.pytorch.org/whl/cpu`
  eklendi; aksi halde `torch==…+cpu` pini Linux'ta PyPI'dan çözülemez.

## Açık sorular (Ozan'ın cevabı bekleniyor)
- [ ] Python 3.13 (CI/Docker) sapmasını onaylıyor musun, yoksa 3.11'e mi dönelim?
- [ ] H1–H3 (LLM sağlayıcı/model, bütçe, fiyatlar) — Faz 4'ten önce gerekli.
- [ ] H5: `docs/plan/forbidden_terms.txt` henüz yok; ilk push'tan önce doldurulmalı.
- [ ] H6: `.env` henüz yok (Faz 4'e kadar gerekmiyor).
- [ ] LICENSE'taki "Ozan Dokur" adı doğru mu?

## Takıldığım yerler
- (yok)
