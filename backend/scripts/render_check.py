"""渲染核验：用 fpbrowser(patchright headless) 真打 localhost:6328，登录后逐页加载，
抓 console error / pageerror / React 是否挂载 / ErrorBoundary 是否触发。
教训落地：build 通过≠能跑，必须真渲染验。用法: python -m scripts.render_check [路由...]
"""
import asyncio, os, sys
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright"))
for v in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy","ALL_PROXY","all_proxy"): os.environ.pop(v, None)
os.environ["NO_PROXY"]="localhost,127.0.0.1"
from fpbrowser import session

BASE="http://127.0.0.1:6328"
ROUTES = sys.argv[1:] or ["/", "/workbench", "/wms/inbound", "/wms/inventory", "/wms/outbound", "/wms/outbound-ledger"]

async def main():
    results=[]
    async with session("photonteck","dev", backend="patchright", proxy=None, headless=True) as bs:
        page = bs.context.pages[0] if bs.context.pages else await bs.context.new_page()
        errs=[]
        page.on("console", lambda m: errs.append(("console.error", m.text)) if m.type=="error" else None)
        page.on("pageerror", lambda e: errs.append(("pageerror", str(e)[:200])))
        # 登录
        await page.goto(BASE+"/login", wait_until="networkidle", timeout=45000)
        try:
            await page.fill("#username","admin"); await page.fill("#password","admin1234")
            await page.click("button[type=submit]"); await page.wait_for_timeout(2500)
            logged = "/login" not in page.url
        except Exception as e:
            logged=False; errs.append(("login-fail", str(e)[:120]))
        print(f"[登录] {'✅成功 ' if logged else '❌失败'} 当前URL={page.url}")
        # 逐页
        for r in ROUTES:
            errs.clear()
            try:
                await page.goto(BASE+r, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                root_children = await page.evaluate("document.getElementById('root')?.children.length || 0")
                body_text = (await page.inner_text("body"))[:0]  # 触发
                has_eb = await page.evaluate("!!document.body.innerText.match(/出错了|Something went wrong|页面崩溃|ErrorBoundary/)")
                page_errs=[e for e in errs]
                status = "❌崩溃" if (has_eb or root_children==0) else ("⚠️有console错" if page_errs else "✅渲染OK")
                print(f"  {r:24} {status} | root子节点={root_children} | 错误{len(page_errs)}条" + (f" → {page_errs[:2]}" if page_errs else ""))
                results.append((r,status,len(page_errs)))
            except Exception as e:
                print(f"  {r:24} ❌加载异常 {str(e)[:80]}"); results.append((r,"加载异常",0))
    ok=sum(1 for _,s,_ in results if s=="✅渲染OK")
    print(f"\n渲染核验: {ok}/{len(results)} 页干净渲染")
asyncio.run(main())
