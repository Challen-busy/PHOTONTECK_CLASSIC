import asyncio, os, sys
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"): os.environ.pop(v,None)
from fpbrowser import session
BASE="http://127.0.0.1:6328"
USER,PW,ROUTE = sys.argv[1], sys.argv[2], sys.argv[3]
async def main():
    async with session("photonteck",USER, backend="patchright", proxy=None, headless=True) as bs:
        page=bs.context.pages[0] if bs.context.pages else await bs.context.new_page()
        errs=[]; page.on("pageerror",lambda e:errs.append(str(e)[:150]))
        await page.goto(BASE+"/login",wait_until="networkidle",timeout=40000)
        await page.fill("#username",USER); await page.fill("#password",PW)
        await page.click("button[type=submit]"); await page.wait_for_timeout(2500)
        await page.goto(BASE+ROUTE,wait_until="networkidle",timeout=30000); await page.wait_for_timeout(1500)
        rc=await page.evaluate("document.getElementById('root')?.children.length||0")
        body=(await page.inner_text("body"))
        has_price = ("对原厂单价" in body) or ("unit_price" in body) or ("佣金" in body)
        print(f"  {USER}@{ROUTE}: root子节点={rc} pageerror={len(errs)} | 含价格/佣金列={'是⚠️' if has_price else '否✅(已遮蔽)'}")
        if errs: print("   errs:",errs[:2])
asyncio.run(main())
