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
  await page.goto("http://127.0.0.1:5000/seller/products/53/edit");
  await page.waitForTimeout(700);
  await page.fill("#discount", "30");
  await page.locator("form button[type=submit]").first().click();
  await page.waitForTimeout(1500);
  const url2 = page.url();
  const flash = await page.evaluate(() => {
    const el = document.querySelector(".alert");
    return el ? el.innerText.slice(0, 150) : "no alert";
  });
  return { url2, flash, errors };
}
