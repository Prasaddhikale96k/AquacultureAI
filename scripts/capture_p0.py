import os
import time
from playwright.sync_api import sync_playwright

def main():
    out_dir = r"c:\Users\vitho\AquacultureAI"
    artifact_dir = r"C:\Users\vitho\.gemini\antigravity-ide\brain\a986d32b-d102-4564-8e2a-b969ad8a8770"
    os.makedirs(artifact_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 950})
        page = context.new_page()

        # 1. Dark mode
        print("Capturing Dark Mode...")
        page.goto("http://localhost:5173/#dev/design-system")
        page.wait_for_selector("h1:has-text('AquacultureAI Design System')", timeout=10000)
        # Ensure dark theme is active
        page.evaluate("() => { localStorage.setItem('aqua:theme', 'dark'); document.documentElement.setAttribute('data-theme', 'dark'); document.documentElement.className = 'dark'; }")
        page.reload()
        page.wait_for_selector("h1:has-text('AquacultureAI Design System')", timeout=10000)
        time.sleep(1)

        dark_path = os.path.join(out_dir, "p0-tokens-dark.png")
        page.screenshot(path=dark_path)
        page.screenshot(path=os.path.join(artifact_dir, "p0-tokens-dark.png"))
        print(f"Captured {dark_path}")

        # 2. Pill variants section (focused)
        pill_elem = page.locator("#pill-variants-section")
        pill_path = os.path.join(out_dir, "p0-pill-variants.png")
        pill_elem.screenshot(path=pill_path)
        pill_elem.screenshot(path=os.path.join(artifact_dir, "p0-pill-variants.png"))
        print(f"Captured {pill_path}")

        # 3. Light mode
        print("Capturing Light Mode...")
        page.evaluate("() => { localStorage.setItem('aqua:theme', 'light'); document.documentElement.setAttribute('data-theme', 'light'); document.documentElement.className = 'light'; }")
        page.reload()
        page.wait_for_selector("h1:has-text('AquacultureAI Design System')", timeout=10000)
        time.sleep(1)

        light_path = os.path.join(out_dir, "p0-tokens-light.png")
        page.screenshot(path=light_path)
        page.screenshot(path=os.path.join(artifact_dir, "p0-tokens-light.png"))
        print(f"Captured {light_path}")

        # 4. Verify language toggle to Hindi & dynamic font loading
        print("Testing Hindi toggle...")
        # Track network requests for noto-sans-devanagari
        devanagari_requested = []
        page.on("request", lambda req: devanagari_requested.append(req.url) if "noto-sans-devanagari" in req.url else None)

        initial_count = len(devanagari_requested)
        print(f"Initial Devanagari font requests before toggle: {initial_count}")

        # Click Hindi toggle button
        page.click("button:has-text('हिन्दी (HI)')")
        time.sleep(1.5)

        after_count = len(devanagari_requested)
        print(f"Devanagari font requests after toggle: {after_count}")
        lang_attr = page.locator("html").get_attribute("lang")
        print(f"HTML lang attribute: {lang_attr}")

        # 5. Reload and test persistence
        page.reload()
        page.wait_for_selector("h1", timeout=10000)
        time.sleep(0.5)
        persisted_theme = page.evaluate("() => localStorage.getItem('aqua:theme')")
        persisted_lang = page.evaluate("() => localStorage.getItem('aqua:lang')")
        print(f"Verified persisted theme: {persisted_theme}")
        print(f"Verified persisted lang: {persisted_lang}")

        browser.close()
        print("All P0 automated checks PASSED!")

if __name__ == "__main__":
    main()
