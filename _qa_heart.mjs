export default async function run(page) {
  const errors = [];
  page.on("dialog", d => d.accept());
  page.on("pageerror", e => errors.push("PAGEERROR " + e.message));
  await page.goto("http://127.0.0.1:5000/auth/login");
  await page.fill("#identifier", "buyer_demo");
  await page.fill("#password", "Buyer@12345");
  await page.click("button[type=submit]");
  await page.waitForTimeout(1200);
  await page.goto("http://127.0.0.1:5000/products");
  await page.waitForTimeout(600);
  await page.screenshot({ path: "C:/Users/user/Documents/NEXACART/_shot_heart.png" });
  // toggle a heart
  await page.locator(".fav-btn").first().click();
  await page.waitForTimeout(700);
  const cls = await page.evaluate(() => document.querySelector(".fav-btn").className);
  // cart page promo box
  await page.goto("http://127.0.0.1:5000/cart/");
  await page.waitForTimeout(500);
  const promoBox = await page.evaluate(() => !!document.getElementById("promo-code"));
  await page.screenshot({ path: "C:/Users/user/Documents/NEXACART/_shot_cartpromo.png" });
  return { errors, cls, promoBox };
}
