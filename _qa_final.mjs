 export default async function run(page) {
  const errors = [];
  page.on("dialog", d => d.accept());
  page.on("pageerror", e => errors.push("PAGEERROR " + e.message));
  page.on("response", r => { if (r.status() >= 400) errors.push(r.status() + " " + r.url()); });
  await page.goto("http://127.0.0.1:5000/auth/login");
  await page.fill("#identifier", "_es1");
  await page.fill("#password", "QA@Password1");
  await page.click("button[type=submit]");
  await page.waitForTimeout(1200);
  // heart layout + badges on catalogue
  await page.goto("http://127.0.0.1:5000/products");
  await page.waitForTimeout(600);
  await page.screenshot({ path: "C:/Users/user/Documents/NEXACART/_shot_layout.png" });
  // cart page with promo box
  await page.goto("http://127.0.0.1:5000/cart/");
  await page.waitForTimeout(500);
  const cartEmpty = await page.evaluate(() => document.querySelector("main").innerText.slice(0, 80));
  return { errors, cartEmpty };
}
