# 安徽、江苏维基百科4A补充名单

`4a-wikipedia.json` 来自维基百科贡献者编写的《国家4A级旅游景区》两个省份章节，**是参考来源，不是官方名录**。官方数据仍单独保存在 `4a-official.json` 和 `5a-official.json`。

本次于 **2026-09-10** 下载，固定修订版本 **94049187**，页面最后修订于 **2026-08-26 05:41**。使用 MediaWiki 官方支持的 `variant=zh-cn` 简体显示版本，没有自行音译或机器猜测简体名称。

| 省份 | 页面声明时期 | 声明数量 | 实际表格条数 | 差异 |
| --- | --- | ---: | ---: | ---: |
| 安徽省 | 截至2025年 | 230 | 230 | 0 |
| 江苏省 | 截至2026年3月 | 239 | 239 | 0 |
| 合计 | 两省日期不同 | 469 | 469 | 0 |

全部469条保留原表名称、城市和4A文字，城市依据表格跨行合并单元格展开，共安徽16市、江苏13市。没有重复条目，没有读取页面末尾的摘牌表，也没有混入日期更旧的《安徽省A级景区列表》以填补数量。没有拆分组合景区或为凑齐计数新增条目。

每条数据保留 `source_type: "wikipedia"`、固定修订链接、来源名称和日期精度。江苏 `as_of` 为 `2026-03`。安徽原文只到年份，因此 `as_of` 为 `null`，`source_period` 为 `2025`、`as_of_precision` 为 `year`，不虚构统计月份。页面修订日期与名单声明的统计日期分开记录。

## 已知后续变化

原469条中，有7条安徽记录存在2026-09-07撤销或降级的更新证据；因此用于当前参考4A匹配的记录为 **462条**。原维基快照保持不变，统一变更记录保存在 `rating-corrections.json`，由应用同时处理旧官方名单、维基名单和旧缓存中的过时等级。

证据是[中国质量新闻网的报道](https://www.cqn.com.cn/zj/content/2026-09/08/content_9171802.htm)及[省厅署名公告的媒体转载](https://finance.sina.com.cn/wm/2026-09-08/doc-inirayqy9516645.shtml)。这两篇2026-09-08文本转述安徽省文旅厅9月7日处理结果；未取得可直接读取的省厅主站原文，因此来源类型明确保留为媒体转述，不伪称官方原始名录。

## 名录差异核对

- 江苏明祖陵与沛县汉城虽在维基的历史摘牌节中，但后来重新评定：明祖陵见[盱眙县政府2020年统计公报](https://www.xuyi.gov.cn/col/14527_858573/art/16960896/16969899954767cZBmihO.html)，沛县汉城见[2023年省厅采访报道](https://www.zgjssw.gov.cn/yaowen/202302/t20230203_7816882.shtml)。未因历史摘牌记录而排除当前主表条目。
- 维基黄山部分23条，[黄山市文旅局2025年9月30日名录](https://www.huangshan.gov.cn/zwgk/public/6615714/11916286.html)为20条。丰乐湖、历溪、黄山虎林园存在目录差异，尚未找到确定取消等级的处理决定，保留维基来源并记为待复核差异，不据官方表缺项推断其已经撤销。

## 许可和归属

依据页面版权说明，提取结果按 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.zh-hans) 署名和相同方式共享。署名为“维基百科贡献者，《国家4A级旅游景区》，修订版本94049187”。

- [固定修订版本（简体）](https://zh.wikipedia.org/w/index.php?title=%E5%9B%BD%E5%AE%B64A%E7%BA%A7%E6%97%85%E6%B8%B8%E6%99%AF%E5%8C%BA&oldid=94049187&variant=zh-cn)
- [贡献者与修订历史](https://zh.wikipedia.org/w/index.php?title=%E5%9B%BD%E5%AE%B64A%E7%BA%A7%E6%97%85%E6%B8%B8%E6%99%AF%E5%8C%BA&action=history)

相对源页面的改动仅为提取两个省份的表格、展开城市跨行单元格、去除脚注编号、转换JSON及增加来源和数量核对元数据。景区名称和原表等级没有根据名称相似度自动改写。

## 复现

生成脚本 `dev/build_wikipedia_4a.py` 只使用Python标准库，不安装依赖、不接触应用数据库。默认下载固定版本和简体变体：

```sh
/Library/Developer/CommandLineTools/usr/bin/python3 dev/build_wikipedia_4a.py --save-html /tmp/scenic-wikipedia/source-zh-cn.html
```

复用本次HTML、保留原抓取日期：

```sh
/Library/Developer/CommandLineTools/usr/bin/python3 dev/build_wikipedia_4a.py --html /tmp/scenic-wikipedia/source-zh-cn.html --retrieved-at 2026-09-10
```

更换修订须显式指定 `--revision` 并重新核验声明数量、实际数量、城市归属及后续等级变化。生成器验证实际收到的修订号与简体变体，并保存原始HTML的SHA-256，防止误把不同快照标为同一来源。
