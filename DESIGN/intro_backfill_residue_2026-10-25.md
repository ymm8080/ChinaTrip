# LLM 简介回填永久残留清单（2026-10-25 收口）

- 回填前空简介 624 条（llm_total 2308/2932）
- 本次会话 15 轮回填入库 549 条（624 空池填掉 87.8%）；期间并行会话入库 ~958 条新 POI（自带简介），active 总数 2932→3890
- 当前简介覆盖率：3814/3890 = 98.0%
- 残留 76 条：模型连续 8 轮 SKIP（~66，多为 OSM 长尾无名点）+ 反复 too_short（~9，短句过不了 40-70 字门槛）+ 偶发错误
- **收口（2026-10-25）：用户确认后 76 条全部软删除（status→inactive），active 池 3814 行空简介清零，简介覆盖率 100%。物理行保留可恢复。**
- **追加（2026-10-25）：704工程(林彪杭州行宫)、孙中山先生故居两条经核实为真实景点，已恢复 active 并写入手工简介（intro_source=manual，事实经百度百科/维基百科/广州市政府官网核实），active 3816 行覆盖率仍 100%。**

| id | source | city | name_zh | category |
|---|---|---|---|---|
| 24b8372a-2333-4e27-8c2d-3540ba87c90c | amap | 上海 | 魔都矩阵 |  |
| d3947aca-216f-4434-b8a0-2fdfd97e36e7 | amap | 北京 | 天宁寺城 |  |
| 1768f0a3-84b4-459c-8557-60baa615ac20 | amap | 南京 | 穿越南京 |  |
| 7af940b7-eb02-4a4f-ab71-e645350a0c00 | amap | 南京 | 世界之窗 |  |
| 3e08bc78-3ccf-4447-a66a-74380f04313d | amap | 广州 | 有马空间(琶洲店) |  |
| 983f1111-6c4b-4ce4-9850-50f2885ce885 | amap | 广州 | 百花园(三堂路店) |  |
| dde24aeb-f8c7-43e8-b3a1-12f7e19aa0b5 | amap | 广州 | 番禺欢乐森林 |  |
| a0e3b32f-2460-4ecf-879f-583c2784b066 | amap | 成都 | 成都鹿尔花园 |  |
| b24dc26e-a480-4852-adf8-cf256e6ca40c | amap | 成都 | 禧来蜀韵园 |  |
| 150c9737-6c9a-4d19-a9c2-a373355f8fb8 | amap | 杭州 | 704工程(林彪杭州行宫) |  |
| 01b3bca6-1897-4962-9b95-41be09a15a22 | amap | 武汉 | 松鼠乐园 |  |
| 188c5c4b-4c0e-4bb2-8088-19188286fed0 | amap | 武汉 | 武汉趣谷 |  |
| 7250cb3a-4532-4ae7-932f-cf99fdda8882 | amap | 武汉 | 嘉诺艺术教堂 |  |
| c70e493e-b321-4c2a-b618-bf25f10c12a9 | amap | 武汉 | 澜庭 |  |
| df8600d1-f76f-4362-a004-528ed594a1c4 | amap | 武汉 | 古巷小吃街 |  |
| a1445ae8-e5da-4107-bbbf-255a3f5e274b | amap | 深圳 | 东家湾沙滩 |  |
| bb1ffa22-9fb4-4104-936f-1fc1ec7a633f | amap | 深圳 | 钱江艺术中心 |  |
| c583b526-3af4-4366-ba34-c274e88bbed1 | amap | 深圳 | 哈特曼航空体验馆 |  |
| bcd50e8b-9bfa-4a28-8678-4dff08fab2f4 | amap | 苏州 | 真趣园 |  |
| c2a104e3-d77d-4b56-a4fe-14fef75c290a | amap | 苏州 | 锦澜沙滩 |  |
| 44a3a587-1ff2-4ba6-8155-6779713d19d8 | amap | 重庆 | 天眼洞花岭 |  |
| abdab380-c423-4f75-b892-92fb22e68f3f | amap | 重庆 | 地心探险极地 |  |
| 13e0bda1-ed75-4583-8a73-ae5321b0f591 | chinatravel | 上海 | 枫叶岛 | theme_park |
| 7744ba41-96f0-4537-aa3c-7094a4385bc0 | chinatravel | 上海 | 叙宴（上海旗舰店） |  |
| 7b89d362-daff-43d1-a5ba-a94760761057 | chinatravel | 上海 | 魔都悬空玻璃剧场 |  |
| 81701e60-b78f-4b0d-8094-dd8b0222877a | chinatravel | 上海 | 云起美术馆 |  |
| f29c96fb-1eb1-48f6-8f7f-421344e54429 | chinatravel | 上海 | 沐屿新集 |  |
| fec5f4cd-1142-4e33-9891-4e415a5f09cc | chinatravel | 上海 | 上海上引+ |  |
| 0a99c245-5fc6-4976-811d-7a764b957ae3 | chinatravel | 北京 | 紫御湾码头 |  |
| 5dd2479b-722f-4f97-9516-d5ff0e70ef36 | chinatravel | 北京 | 北京戏剧嘉年华 | theme_park |
| b606ace6-bb47-4030-b34b-2d7f33514edf | chinatravel | 北京 | 奥加美术馆 |  |
| 03ace63a-916b-43c4-ba64-88f03c2a670a | chinatravel | 南京 | 南京近代建筑博物馆 | museum |
| 20d6c2c9-e51a-42eb-beb3-0af40edda77c | chinatravel | 南京 | 南京长城 |  |
| 28b81f64-d9d2-4ce0-82df-22331d859d83 | chinatravel | 南京 | 徐家大院 |  |
| c8230fcf-42b0-485a-be83-37a6bb833922 | chinatravel | 南京 | 云水兰亭 |  |
| 02176265-5bf6-4496-bba2-e7cd9fb3457f | chinatravel | 广州 | 考拉广场 |  |
| 4b69106f-ebdf-43fc-ac28-18ba7196f048 | chinatravel | 广州 | 韩江屋 |  |
| 76186933-00b7-4f2e-b6f5-61cf8b1fbea1 | chinatravel | 广州 | 乘船探索秘境 | nature |
| 86be796d-b482-443e-90db-5d0edff417b6 | chinatravel | 广州 | 孙中山先生故居 |  |
| b65b21a6-dad3-4051-8e1a-8cb6f1d6ebe9 | chinatravel | 广州 | 中央演艺广场 |  |
| c0fa4638-4d86-4b68-8279-142f6012a083 | chinatravel | 广州 | 广州山谷国际旅游度假区 | theme_park |
| 345ecb0a-a099-46d1-a158-015c5152cf75 | chinatravel | 成都 | 戏蝶剧社 |  |
| 3ff15131-6fa2-4df7-934e-1c1732a831e4 | chinatravel | 成都 | 黄龙洞 | nature |
| 6b8875f8-a077-4083-9373-0e34929191f7 | chinatravel | 成都 | 新尚公馆·水韵Plus |  |
| 729230cf-47bb-4c81-b034-f38b132d7594 | chinatravel | 成都 | 壹耳阁 |  |
| 8a2454e5-36e4-4136-bc6c-dfc9c7c4607b | chinatravel | 成都 | 生机之塔 | theme_park |
| c6bb1d41-6153-4cd7-b158-7b14b6f90284 | chinatravel | 成都 | 穿越成都 |  |
| ffa5dc79-ac3b-44c4-8fdc-1ff4cd24b68b | chinatravel | 成都 | 游玩攻略·潮玩街区 |  |
| 0f64281e-c482-4a07-9114-d21fefc5b89c | chinatravel | 杭州 | 望湖楼茶餐厅 |  |
| 32b85aba-f59d-41f1-87a8-6c151b9ad9dc | chinatravel | 杭州 | 蚂蚁工坊 |  |
| 6bbc10b5-b485-42fa-96ae-f60c324c35fb | chinatravel | 杭州 | 梅竹山庄 |  |
| 76297fed-566c-46ed-8cf7-85c1a9b83f93 | chinatravel | 杭州 | 彩虹谷 | theme_park |
| bd36efb8-8fa2-4305-9768-90e659622b55 | chinatravel | 杭州 | 杭州曲水兰亭 |  |
| 34148556-864d-4831-88ec-dda6bbb2735c | chinatravel | 武汉 | 穿越武汉 |  |
| 7796bf35-0608-41ed-8278-eec7df8048ed | chinatravel | 武汉 | 宿于山野 | nature |
| ace6bb4b-f435-4f0a-8183-07b0c2153c9a | chinatravel | 武汉 | 武汉赶海公园 | park |
| 653f60c4-f158-429b-8e6f-050ef2bf373d | chinatravel | 深圳 | 香格里拉雪域 | nature |
| 9cd78068-ce49-491e-97c3-e8067321cc23 | chinatravel | 深圳 | 天涯海角 | nature |
| a5bc0661-7392-4d1e-9295-445d95a534b8 | chinatravel | 深圳 | 深圳天空之城 | theme_park |
| c2885cfe-ca3a-4664-9585-e0056697e124 | chinatravel | 深圳 | 弘源寺 |  |
| 05db3c59-d539-47ee-9d27-9a89a77a02e7 | chinatravel | 苏州 | 憩园 |  |
| 16b0630a-608b-4f1c-8098-03696e593666 | chinatravel | 苏州 | 山门夕照 |  |
| 17c112b8-5072-4df1-a042-6bdec98d4fa3 | chinatravel | 苏州 | 南山鬼校 | theme_park |
| 54013b94-31c3-4c9d-a5f9-ce6756737139 | chinatravel | 苏州 | 嘎嘎部落 |  |
| 55a8b76f-a7b7-478a-a6a1-8ccd2661a31c | chinatravel | 苏州 | 太平桥 |  |
| 5d3e9f93-32e5-4843-982a-200758adc4b2 | chinatravel | 苏州 | 南湖 |  |
| 60938cbf-bd8d-4be0-8d3a-dd2385b51d27 | chinatravel | 苏州 | 南门坛上 |  |
| 7bea08f8-0ba7-4788-82e3-0eb24871f489 | chinatravel | 苏州 | 澄园 |  |
| a0317fca-08ae-44a9-84a5-3c149dcd3ea6 | chinatravel | 苏州 | 凤凰台 |  |
| b9035398-377c-4d9b-adc1-0fd1aa58bdc9 | chinatravel | 苏州 | 南湖秋月园 |  |
| c03842b1-d51f-4420-8ac8-4eca0637ad3d | chinatravel | 苏州 | 非诚勿扰 |  |
| c5f5762f-db47-430e-91ba-c69397af00db | chinatravel | 苏州 | 白鹤寺 |  |
| ef4cb014-85e5-47f5-9ffc-f316ec60af19 | chinatravel | 苏州 | 别有洞天 |  |
| 3523a879-0bf7-4374-bda3-2dcb4ccca2a7 | chinatravel | 重庆 | 重庆望仙谷 |  |
| 47802622-77cc-4464-ac06-b69d5d98ee19 | chinatravel | 重庆 | 洞舰1号 |  |
| a1e1199e-0f6f-45f9-b792-b50fc007e8b1 | chinatravel | 重庆 | 七里塘 | park |