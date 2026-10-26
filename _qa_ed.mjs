export default async function run(page) {
  const errors = [];
  page.on("pageerror", e => errors.push("PAGEERROR " + e.message));
  page.on("response", r => { if (r.status() >= 400) errors.push(r.status() + " " + r.url()); });
  await page.goto("http://127.0.0.1:5000/auth/login");
  await page.fill("#identifier", "seller_demo");
  await page.fill("#password", "Seller@12345");
  await page.click("button[type=submit]");
  await page.waitForTimeout(1200);
  const url = page.url();
  await page.goto("http://127.0.0.1:5000/products");
  await page.waitForTimeout(700);
  const editLinks = await page.evaluate(() => document.querySelectorAll("a[href*='edit']").length);
  return { url, editLinks, errors };
}
