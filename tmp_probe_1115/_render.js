
const rows = [];
const blk = { appendChild: (h) => rows.push(h) };
const el = (h) => h;
const esc = (s) => String(s == null ? "" : s);
const dict = {"card.hop.title": "🚏 接驳路线：", "card.hop.taxi": "🚕 打车到 {stop} {km} km · 约 {n} 分钟", "card.hop.ride": "🚌 {name} {depart} 发车 · 车程约 {n} 分钟", "card.hop.wait": "（候车 {n} 分钟）", "card.hop.walk": "🚶 {stop} 下车 · 步行 {n} 分钟", "card.hop.times": "🕘 班次 {times}", "card.hop.returns": "返程 {times}", "card.hop.cost": "打车约 ¥{a} + 接驳约 ¥{b}", "card.hop.book": "购票/预约 →", "card.hop.official": "官网 →"};
const I18N = { tf: (k, zh) => (dict[k] != null ? dict[k] : (zh != null ? zh : k)) };
const it = { next_leg_detail: {"mode": "access", "taxi_km": 0.98, "taxi_minutes": 16, "wait_minutes": 44, "service_minutes": 90, "walk_minutes": 8, "gateway": "前门大街北口（北京旅游集散中心发车点）", "alight": "慕田峪长城 P1/P4 停车场", "service_name": "前门旅游专线（前门大街北口）", "operator": "北京旅游集散中心", "departures": ["07:30", "08:30", "09:30", "10:30"], "returns": ["14:30", "15:30", "16:30"], "fare_text": "官网未公布专线车费；运营方咨询 010-83531111", "board_time": "08:46", "depart_time": "09:30", "arrive_time": "11:08", "taxi_cost": 13, "access_cost": 20, "booking_url": "https://en.mutianyugreatwall.com/pdf/one-day", "official_url": "https://en.mutianyugreatwall.com/pdf/one-day"} };
const ind = "";
          // 接驳路线拆分（2026-11-16 用户拍板：酒店→专线上车点（距离+时间）→专线车程→下车步行，
          // 并给班次、票价、购票/官网链接）。数据全部来自后端 next_leg_detail。
          const legD = it.next_leg_detail;
          if (legD && legD.service_name !== undefined && (legD.mode === "access" || legD.taxi_km != null)) {
            const kmTxt = (Number(legD.taxi_km) || 0).toFixed(1);
            const hops = [];
            if ((Number(legD.taxi_km) || 0) > 0.05) {
              hops.push(I18N.tf("card.hop.taxi", "🚕 打车到 {stop} {km} km · 约 {n} 分钟")
                .replace("{stop}", esc(legD.gateway || ""))
                .replace("{km}", kmTxt)
                .replace("{n}", String(legD.taxi_minutes || 0)));
            }
            if (legD.service_name) {
              let ride = I18N.tf("card.hop.ride", "🚌 {name} {depart} 发车 · 车程约 {n} 分钟")
                .replace("{name}", esc(legD.service_name))
                .replace("{depart}", legD.depart_time || I18N.tf("card.hop.asap", "首班后随到随走"))
                .replace("{n}", String(legD.service_minutes || 0));
              if ((legD.wait_minutes || 0) > 0) ride += I18N.tf("card.hop.wait", "（候车 {n} 分钟）").replace("{n}", String(legD.wait_minutes));
              hops.push(ride);
            }
            if ((legD.walk_minutes || 0) > 0) {
              hops.push(I18N.tf("card.hop.walk", "🚶 {stop} 下车 · 步行 {n} 分钟")
                .replace("{stop}", esc(legD.alight || legD.gateway || ""))
                .replace("{n}", String(legD.walk_minutes)));
            }
            if (hops.length) {
              blk.appendChild(el('<div class="muted" style="margin:0 2px 6px ' + ind + '">' + I18N.tf("card.hop.title", "🚏 接驳路线：") + hops.join(" → ") + "</div>"));
            }
            const when = [];
            if (Array.isArray(legD.departures) && legD.departures.length) {
              when.push(I18N.tf("card.hop.times", "🕘 班次 {times}").replace("{times}", legD.departures.join(" / ")));
            }
            if (Array.isArray(legD.returns) && legD.returns.length) {
              when.push(I18N.tf("card.hop.returns", "返程 {times}").replace("{times}", legD.returns.join(" / ")));
            }
            if ((legD.taxi_cost || 0) + (legD.access_cost || 0) > 0) {
              when.push(I18N.tf("card.hop.cost", "打车约 ¥{a} + 接驳约 ¥{b}")
                .replace("{a}", String(legD.taxi_cost || 0)).replace("{b}", String(legD.access_cost || 0)));
            }
            if (when.length) blk.appendChild(el('<div class="muted" style="margin:0 2px 6px ' + ind + '">' + when.join(" · ") + "</div>"));
            const ticket = [];
            if (legD.fare_text) ticket.push("🎟 " + esc(legD.fare_text));
            if (legD.booking_url) ticket.push('<a class="leg-link" target="_blank" rel="noopener" href="' + esc(legD.booking_url) + '">' + I18N.tf("card.hop.book", "购票/预约 →") + "</a>");
            if (legD.official_url && legD.official_url !== legD.booking_url) ticket.push('<a class="leg-link" target="_blank" rel="noopener" href="' + esc(legD.official_url) + '">' + I18N.tf("card.hop.official", "官网 →") + "</a>");
            if (ticket.length) blk.appendChild(el('<div class="muted" style="margin:0 2px 6px ' + ind + '">' + ticket.join(" · ") + "</div>"));
          }

console.log(rows.join("\n---\n"));
