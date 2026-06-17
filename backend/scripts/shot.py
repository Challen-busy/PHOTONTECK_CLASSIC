import asyncio, os
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"): os.environ.pop(v,None)
from fpbrowser import session
BASE="http://127.0.0.1:6328"; OUT="/tmp/ptk_shots"
os.makedirs(OUT, exist_ok=True)
async def main():
    async with session("photonteck","dev", backend="patchright", proxy=None, headless=True) as bs:
        page=bs.context.pages[0] if bs.context.pages else await bs.context.new_page()
        await page.set_viewport_size({"width":1440,"height":900})
        await page.goto(BASE+"/login",wait_until="networkidle",timeout=40000)
        await page.fill("#username","admin"); await page.fill("#password","admin1234")
        await page.click("button[type=submit]"); await page.wait_for_timeout(2500)
        shots=[("workbench","/"),("doc_editor_engine","/node/15/PENDING"),("inbound_biz","/wms/inbound")]
        for name,route in shots:
            await page.goto(BASE+route,wait_until="networkidle",timeout=30000); await page.wait_for_timeout(2000)
            await page.screenshot(path=f"{OUT}/{name}.png", full_page=False)
            print(f"  截 {name} <- {route}")
        # 业务抽屉: 点入库台账第一行
        try:
            await page.goto(BASE+"/wms/inbound",wait_until="networkidle",timeout=30000); await page.wait_for_timeout(1800)
            await page.click(".ant-table-row", timeout=5000); await page.wait_for_timeout(1800)
            await page.screenshot(path=f"{OUT}/inbound_drawer_biz.png", full_page=False)
            print("  截 inbound_drawer_biz <- /wms/inbound 点行抽屉")
        except Exception as e: print("  抽屉截图跳过:", str(e)[:80])
asyncio.run(main())
print("OUT:", OUT)
