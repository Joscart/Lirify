"""Verify the built Astro app against the real FastAPI route with fixture data."""

from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
import os
import subprocess
import sys
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "services" / "web"
URL = "http://127.0.0.1:4321/"


@contextmanager
def running(command, cwd, url, env=None):
    process = subprocess.Popen(command, cwd=cwd, env=env)
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Server exited with status {process.returncode}: {command[0]}")
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.2)
        else:
            raise RuntimeError(f"Server did not respond at {url}")
        yield
    finally:
        process.terminate()
        process.wait(timeout=10)


def check_browser(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    page.route("https://**/*", lambda route: route.abort())
    page.goto(URL)
    heading = page.get_by_role("heading", name="Encuentra una canción por su letra")
    expect(heading).to_be_visible()
    expect(page.locator("#course-catalogue-content .track-row")).to_have_count(8)
    expect(page).to_have_title("UPSpotify · Busca canciones por su letra")
    theme = page.get_by_role("button", name="Modo oscuro")
    expect(theme).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Ir al contenido")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("#view")).to_be_focused()

    theme.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.reload()
    expect(theme).to_have_attribute("aria-pressed", "false")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    query = page.get_by_role("searchbox", name="Palabra o frase de la canción")
    query.fill("amor")
    query.press("Enter")
    expect(page.get_by_role("heading", name="«amor»")).to_be_visible()
    expect(page.get_by_text("10 resultados · 14 canciones en el índice")).to_be_visible()
    rows = page.locator(".course-result-list > li")
    expect(rows).to_have_count(10)
    expect(rows.first.locator("blockquote")).to_contain_text("Mi amor es eterno")
    expect(rows.first.locator("details li")).to_have_count(3)
    toggle = rows.nth(1).locator("summary")
    toggle.focus()
    toggle.press("Enter")
    expect(rows.nth(1).locator("details[open] li")).to_have_count(3)
    expect(rows.nth(1).get_by_role("button", name="Reproducir Canción 10")).to_be_visible()
    page.route("**/api/player/stream/**", lambda route: route.fulfill(status=404, body="{}"))
    rows.first.get_by_role("button", name="Reproducir Canción 0", exact=True).click()
    page.locator("#btn-lyrics-top").click()
    expect(page.locator("#lyrics-list .lyric-line").first).to_contain_text("Mi amor es eterno")
    expect(page.locator("#lyrics-sync")).to_contain_text("Sincronizada")
    page.locator("#lyrics-expand").click()
    expect(page.locator("#lyrics-panel")).to_have_class("lyrics-panel is-expanded")
    page.locator("#lyrics-close").click()
    page.locator("#lyrics-close").click()
    expect(page.locator("#lyrics-panel")).to_have_attribute("aria-hidden", "true")

    page.set_viewport_size({"width": 360, "height": 780})
    expect(rows.first.get_by_role("button", name="Reproducir Canción 0")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth"), "Mobile page overflows"
    assert page.locator("#view-scroll").evaluate(
        "(element) => element.scrollWidth <= element.clientWidth"
    ), "Mobile results overflow"
    theme.click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    topbar = page.get_by_role("searchbox", name="Busca una canción por su letra")
    topbar.fill("sincoincidencia")
    topbar.press("Enter")
    expect(page.get_by_text("No encontramos coincidencias en las letras.", exact=False)).to_be_visible()
    request = "**/api/player/course-search?*"
    page.route(request, lambda route: route.abort())
    topbar.fill("fuego")
    topbar.press("Enter")
    expect(page.get_by_role("alert")).to_contain_text("El buscador no respondió")
    page.unroute(request)
    page.get_by_role("button", name="Reintentar").click()
    expect(page.get_by_text("No encontramos coincidencias en las letras.", exact=False)).to_be_visible()

    page.goto(URL)
    expect(heading).to_be_visible()
    page.get_by_role("link", name="Ver todas").click()
    expect(page.locator("#library-body .track-row")).to_have_count(14)
    page.get_by_role("searchbox", name="Filtrar por título o artista").fill("Canción 13")
    expect(page.locator("#library-body .track-row")).to_have_count(1)
    page.goto(URL)
    page.get_by_role("link", name="Agregar una playlist al catálogo").click()
    expect(page.get_by_role("heading", name="Agregar canciones")).to_be_visible()
    page.get_by_label("Enlace de la playlist").fill("https://music.youtube.com/playlist?list=PLfixture123456789")
    page.get_by_role("button", name="Importar", exact=True).click()
    expect(page.locator("#import-status")).to_contain_text("En cola")
    page.goto(URL)
    page.get_by_role("combobox", name="Idioma").select_option("en")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.get_by_role("heading", name="Find a song by its lyrics")).to_be_visible()
    expect(page.get_by_role("link", name="Add a playlist to the catalogue")).to_have_attribute(
        "href", "#/import"
    )
    page.goto(URL)
    expect(page.locator("html")).to_have_attribute("lang", "en")
    page.close()


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(ROOT / "services" / "api" / "app")}
    backend = [sys.executable, "services/api/tests/serve_fixture.py"]
    frontend = ["node", "dist/server/entry.mjs"]
    web_env = {**env, "HOST": "127.0.0.1", "PORT": "4321",
               "PYTHON_BACKEND_URL": "http://127.0.0.1:8000", "GRPC_TARGET": "127.0.0.1:50051"}
    with running(backend, ROOT, "http://127.0.0.1:8000/health", env):
        with running(frontend, WEB, f"{URL}health", web_env), sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                check_browser(browser)
            finally:
                browser.close()
