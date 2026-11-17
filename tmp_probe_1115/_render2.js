
const rows = [];
const blk = { appendChild: (h) => rows.push(h) };
const el = (h) => h;
const esc = (s) => String(s == null ? "" : s);
const dict = {"card.hop.valTaxi": "打车 {km} km · 约 {n} 分钟 → {stop}", "card.hop.departAt": "{t} 发车", "card.hop.rideMin": "车程 {n} 分钟", "card.hop.waitMin": "候车 {n} 分钟", "card.hop.walkMin": "下车步行 {n} 分钟", "card.hop.arriveAt": "约 {t} 到", "card.hop.cost": "打车约 ¥{a} + 接驳约 ¥{b}", "card.hop.book": "购票/预约 →", "card.hop.official": "官网 →", "card.hop.times": "班次 {times}", "card.hop.returns": "返程 {times}"};
const I18N = { tf: (k, zhText) => (dict[k] != null ? dict[k] : (zhText != null ? zhText : k)) };
const it = { next_leg_detail: {"mode": "access", "taxi_km": 0.98, "taxi_minutes": 16, "wait_minutes": 44, "service_minutes": 90, "walk_minutes": 8, "gateway": "前门大街北口（北京旅游集散中心发车点）", "alight": "慕田峪长城 P1/P4 停车场", "service_name": "前门旅游专线（前门大街北口）", "departures": ["07:30", "08:30", "09:30", "10:30"], "returns": ["14:30", "15:30", "16:30"], "fare_text": "官网未公布专线车费；运营方咨询 010-83531111", "board_time": "08:46", "depart_time": "09:30", "arrive_time": "11:08", "taxi_cost": 13, "access_cost": 20, "booking_url": "https://en.mutianyugreatwall.com/reservation-center/tickets", "official_url": "https://en.mutianyugreatwall.com/pdf/one-day"} };
          // 接驳路线箱（2026-11-16 用户拍板「TRANSPORTATION SHOULD SHOW LEG CLEARLY」；
          // 三拍：固定三行——①打车到乘车点（距离+分钟）②专线车程（发车+候车+步行+到达）
          // ③费用与购票/官网链接；班次/返程/票价原文放 title，不占视觉行。
          const legD = it.next_leg_detail;
          if (legD && legD.service_name !== undefined && (legD.mode === "access" || legD.taxi_km != null)) {
            const rows = [];
            if ((Number(legD.taxi_km) || 0) > 0.05) {
              rows.push('<div class="lr"><span class="li">\uD83D\uDE95</span><span class="lv">' +
                I18N.tf("card.hop.valTaxi", "打车 {km} km · 约 {n} 分钟 → {stop}")
                  .replace("{km}", (Number(legD.taxi_km) || 0).toFixed(1))
                  .replace("{n}", String(legD.taxi_minutes || 0))
                  .replace("{stop}", esc(legD.gateway || "")) + "</span></div>");
            }
            if (legD.service_name) {
              const parts = [];
              parts.push(esc(legD.service_name));
              if (legD.depart_time) parts.push(I18N.tf("card.hop.departAt", "{t} 发车").replace("{t}", legD.depart_time));
              parts.push(I18N.tf("card.hop.rideMin", "车程 {n} 分钟").replace("{n}", String(legD.service_minutes || 0)));
              if ((legD.wait_minutes || 0) > 0) parts.push(I18N.tf("card.hop.waitMin", "候车 {n} 分钟").replace("{n}", String(legD.wait_minutes)));
              if ((legD.walk_minutes || 0) > 0) parts.push(I18N.tf("card.hop.walkMin", "下车步行 {n} 分钟").replace("{n}", String(legD.walk_minutes)));
              if (legD.arrive_time) parts.push(I18N.tf("card.hop.arriveAt", "约 {t} 到").replace("{t}", legD.arrive_time));
              rows.push('<div class="lr"><span class="li">\uD83D\uDE8C</span><span class="lv">' + parts.join(" \u00b7 ") + "</span></div>");
            }
            const pay = [];
            if ((legD.taxi_cost || 0) + (legD.access_cost || 0) > 0) {
              pay.push(I18N.tf("card.hop.cost", "打车约 ¥{a} + 接驳约 ¥{b}")
                .replace("{a}", String(legD.taxi_cost || 0)).replace("{b}", String(legD.access_cost || 0)));
            }
            if (legD.booking_url) pay.push('<a class="leg-link" target="_blank" rel="noopener" href="' + esc(legD.booking_url) + '">' + I18N.tf("card.hop.book", "购票/预约 →") + "</a>");
            if (legD.official_url && legD.official_url !== legD.booking_url) pay.push('<a class="leg-link" target="_blank" rel="noopener" href="' + esc(legD.official_url) + '">' + I18N.tf("card.hop.official", "官网 →") + "</a>");
            if (pay.length) {
              const tips = [];
              if (Array.isArray(legD.departures) && legD.departures.length) tips.push(I18N.tf("card.hop.times", "班次 {times}").replace("{times}", legD.departures.join(" / ")));
              if (Array.isArray(legD.returns) && legD.returns.length) tips.push(I18N.tf("card.hop.returns", "返程 {times}").replace("{times}", legD.returns.join(" / ")));
              if (legD.fare_text) tips.push(legD.fare_text);
              const titleAttr = tips.length ? ' title="' + esc(tips.join(" · ")) + '"' : "";
              rows.push('<div class="lr"><span class="li">\uD83C\uDF9F</span><span class="lv"' + titleAttr + ">" + pay.join(" \u00b7 ") + "</span></div>");
            }
            if (rows.length) blk.appendChild(el('<div class="legbox">' + rows.join("") + "</div>"));
          }

const html = rows.join("\n");
console.log(html);
for (const m of html.matchAll(/<div class="lr">([\s\S]*?)<\/div>/g)) {
  console.log("LINE:", m[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}
