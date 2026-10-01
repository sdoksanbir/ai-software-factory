from factory.task_router import route_task


def test_summary_is_read():
    route = route_task(
        "Projenin mevcut yapisini kisa sekilde ozetle."
    )

    assert route.kind == "read"


def test_explain_is_read():
    route = route_task(
        "factory/orchestrator.py ne yapiyor, acikla."
    )

    assert route.kind == "read"


def test_analysis_is_read():
    route = route_task(
        "Bu projeyi incele ve mimarisini analiz et."
    )

    assert route.kind == "read"


def test_create_function_is_write():
    route = route_task(
        (
            "math_utils.py dosyasinda "
            "multiply(a, b) fonksiyonu olustur."
        )
    )

    assert route.kind == "write"


def test_fix_bug_is_write():
    route = route_task(
        "React component icindeki hatayi duzelt."
    )

    assert route.kind == "write"


def test_add_tests_is_write():
    route = route_task(
        "factorial fonksiyonunu incele ve testlerini ekle."
    )

    # Hem READ hem WRITE sinyali var.
    # Degisiklik talebi daha oncelikli.
    assert route.kind == "write"


def test_unknown_defaults_to_read():
    route = route_task(
        "Bu proje hakkinda bilgi ver."
    )

    assert route.kind == "read"


def test_empty_prompt_rejected():
    try:
        route_task("   ")
    except ValueError:
        return

    raise AssertionError(
        "Bos prompt ValueError vermeliydi."
    )


def test_virtualenv_setup_is_execute():
    route = route_task(
        "Ana klasore venv sanal ortami kur."
    )
    assert route.kind == "execute"


def test_virtualenv_create_is_execute():
    route = route_task(
        "Proje kokunde .venv olustur."
    )
    assert route.kind == "execute"


def test_virtualenv_explanation_stays_read():
    route = route_task(
        "venv sanal ortami nedir, acikla."
    )
    assert route.kind == "read"


def test_pip_setup_is_execute():
    route = route_task(
        "Simdi bu klasore pip kurulumunu gerceklestir."
    )
    assert route.kind == "execute"


def test_pip_install_is_execute():
    route = route_task(
        "Bu projede pip install islemini gerceklestir."
    )
    assert route.kind == "execute"


def test_pip_explanation_stays_read():
    route = route_task(
        "pip nedir, acikla."
    )
    assert route.kind == "read"


# --- Compound WRITE: artifact + ambiguous creation verb ---


def test_html_prototype_yap_is_write():
    route = route_task(
        "bana statik bir HTML tasarım prototipi yap"
    )
    assert route.kind == "write"


def test_html_tasarimi_hazirla_is_write():
    route = route_task(
        "HTML tasarımı hazırla"
    )
    assert route.kind == "write"


def test_web_sayfasi_tasarla_is_write():
    route = route_task(
        "web sayfası tasarla"
    )
    assert route.kind == "write"


def test_react_component_hazirla_is_write():
    route = route_task(
        "React component hazırla"
    )
    assert route.kind == "write"


def test_css_prototipi_olustur_is_write():
    route = route_task(
        "CSS prototipi oluştur"
    )
    assert route.kind == "write"


def test_login_ekrani_yap_is_write():
    route = route_task(
        "login ekranı yap"
    )
    assert route.kind == "write"


def test_dashboard_arayuzu_hazirla_is_write():
    route = route_task(
        "dashboard arayüzü hazırla"
    )
    assert route.kind == "write"


def test_mixed_incele_and_html_prototype_is_write():
    route = route_task(
        "projeyi incele ve HTML prototipi yap"
    )
    assert route.kind == "write"


def test_python_dosyasi_olustur_is_write():
    route = route_task(
        "yeni bir Python dosyası oluştur"
    )
    assert route.kind == "write"


def test_readme_bolum_ekle_is_write():
    route = route_task(
        "README'ye bölüm ekle"
    )
    assert route.kind == "write"


def test_fonksiyonu_duzelt_is_write():
    route = route_task(
        "bu fonksiyonu düzelt"
    )
    assert route.kind == "write"


def test_reversed_yap_html_prototype_is_write():
    route = route_task(
        "yap bir HTML prototipi"
    )
    assert route.kind == "write"


# --- READ: analysis and bare ambiguous verbs ---


def test_repo_analizi_yap_is_read():
    route = route_task(
        "repo analizi yap"
    )
    assert route.kind == "read"


def test_dosya_analizi_yap_is_read():
    route = route_task(
        "dosya analizi yap"
    )
    assert route.kind == "read"


def test_kodlari_incele_is_read():
    route = route_task(
        "kodları incele"
    )
    assert route.kind == "read"


def test_dosyayi_acikla_is_read():
    route = route_task(
        "bu dosyayı açıkla"
    )
    assert route.kind == "read"


def test_mimariyi_analiz_et_is_read():
    route = route_task(
        "mimariyi analiz et"
    )
    assert route.kind == "read"


def test_hatanin_nedenini_bul_is_read():
    route = route_task(
        "hatanın nedenini bul"
    )
    assert route.kind == "read"


def test_projeyi_anlat_is_read():
    route = route_task(
        "bana projeyi anlat"
    )
    assert route.kind == "read"


def test_kodu_degerlendir_is_read():
    route = route_task(
        "mevcut kodu değerlendir"
    )
    assert route.kind == "read"


def test_html_yapisi_analiz_et_is_read():
    route = route_task(
        "HTML yapısını analiz et"
    )
    assert route.kind == "read"


def test_dashboard_incele_is_read():
    route = route_task(
        "dashboard'u incele"
    )
    assert route.kind == "read"


def test_bare_bir_sey_yap_is_read():
    route = route_task(
        "bir şey yap"
    )
    assert route.kind == "read"


def test_bare_ne_yapmaliyim_is_read():
    route = route_task(
        "ne yapmalıyım"
    )
    assert route.kind == "read"


# --- EXECUTE: narrow run intents ---


def test_testleri_calistir_is_execute():
    route = route_task(
        "testleri çalıştır"
    )
    assert route.kind == "execute"


def test_pytest_calistir_is_execute():
    route = route_task(
        "pytest çalıştır"
    )
    assert route.kind == "execute"


def test_python_script_calistir_is_execute():
    route = route_task(
        "python script.py çalıştır"
    )
    assert route.kind == "execute"


def test_build_al_is_execute():
    route = route_task(
        "build al"
    )
    assert route.kind == "execute"


def test_lint_calistir_is_execute():
    route = route_task(
        "lint çalıştır"
    )
    assert route.kind == "execute"


# --- WRITE / EXECUTE distinction ---


def test_test_ekle_is_write():
    route = route_task(
        "test ekle"
    )
    assert route.kind == "write"


def test_testlerini_ekle_is_write():
    route = route_task(
        "testlerini ekle"
    )
    assert route.kind == "write"


def test_venv_olustur_is_execute():
    route = route_task(
        "venv oluştur"
    )
    assert route.kind == "execute"


# --- Negative regression: do not over-match ---


def test_html_nedir_is_read():
    route = route_task(
        "HTML nedir?"
    )
    assert route.kind == "read"


def test_react_component_yapisi_acikla_is_read():
    route = route_task(
        "React component yapısını açıkla"
    )
    assert route.kind == "read"


def test_dashboard_analizi_yap_is_read():
    route = route_task(
        "dashboard analizi yap"
    )
    assert route.kind == "read"


def test_pytest_nedir_is_read():
    route = route_task(
        "pytest nedir?"
    )
    assert route.kind == "read"


def test_build_sistemi_is_read():
    route = route_task(
        "build sistemi nasıl çalışıyor?"
    )
    assert route.kind == "read"


def test_python_scriptlerini_incele_is_read():
    route = route_task(
        "python scriptlerini incele"
    )
    assert route.kind == "read"
