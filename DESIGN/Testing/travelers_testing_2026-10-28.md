# 出行人资料（代客预订客户资料）测试文档

| | |
|---|---|
| 版本 | v1.0（2026-10-28） |
| 对应功能 | `DESIGN/travelers_function_spec_2026-10-28.docx` |
| 被测代码 | `app/services/travelers.py` · `app/api/travelers.py` · H5 个人主页分区 |
| 测试文件 | `CHINATRIP CODES/tests/test_travelers_api.py`（9 项） |
| 最新结果 | **9/9 通过**；全量回归 1383 通过 / 0 失败（2026-10-28，连续多轮复验全绿） |

## 1. 测试范围与方法

- **单元/存储层**：TravelerStore 加密落盘、脱敏、审计、归属隔离、物理删除（tmp_path 独立库文件）。
- **API 层**：TestClient 走真实 app 路由（monkeypatch 服务单例指向临时库），覆盖守卫与错误码。
- **前端守门**：H5 静态守门（`node ops/check_h5_static.js`）验证 i18n 词典覆盖与中文残留。
- 隐私断言为硬断言：**直接读取 SQLite 库文件字节，明文证件号/手机号不得出现**。

运行方式：

```bash
cd "CHINATRIP CODES"
.venv/Scripts/python -m pytest tests/test_travelers_api.py -q        # 本功能 9 项
node ops/check_h5_static.js                                          # H5 静态守门
.venv/Scripts/python -m pytest -q                                    # 全量回归
```

## 2. 用例清单与结果

### 2.1 存储层（TravelerStore）

| # | 用例 | 验证点 | 结果 |
|---|---|---|---|
| 1 | test_store_roundtrip_encrypted_at_rest | 库文件字节中无明文证件号/手机号；重启重载后列表只回脱敏形 `E1234**78`；export 才回明文 | ✅ |
| 2 | test_consent_required | consent=false 抛 InvalidTraveler（consent_required） | ✅ |
| 3 | test_owner_isolation_and_delete_all | device/账号归属互相不可见；delete_all 返回条数；物理删除后库中无残留行 | ✅ |
| 4 | test_audit_trail_records_actions_not_values | 审计序列 create→update→export；iterdump 全文无任何字段值 | ✅ |
| 5 | test_update_masks_new_number | 修改证件号后脱敏形更新为 `PE123**56`，export 回新明文 | ✅ |
| 6 | test_too_many_travelers | 第 21 条触发 too_many_travelers | ✅ |
| 7 | test_short_doc_number_masked | ≤7 位短证件号全星 `****` | ✅ |

### 2.2 API 层

| # | 用例 | 验证点 | 结果 |
|---|---|---|---|
| 8 | test_api_full_flow | POST 201 脱敏形且无明文字段；GET 列表带同意书文案；PUT 200；export 回明文；DELETE 204 后 404 | ✅ |
| 9 | test_api_guards | 缺设备头 400；consent=false 422 `consent_required`；非法证件类型 422 `invalid_doc_type`；清空空列表返回 deleted=0 | ✅ |

### 2.3 前端守门

| 检查 | 验证点 | 结果 |
|---|---|---|
| H5 静态守门 | en 词典覆盖全部在用 key（含 me.tv.* 24 条）；JS 中文兜底串白名单化（TV_DOC_ZH）后残留门 0 违例 | ✅ |
| 全量回归 | 1383 通过 / 0 失败（travelers 未破坏任何既有模块；plan 域历史红灯由对应会话修复后归零） | ✅ |

## 3. 隐私合规验收清单

| 合规要求 | 验收方式 | 结果 |
|---|---|---|
| 加密存储（PIPL §51 / GDPR Art.32） | 用例 1 字节级断言 | ✅ |
| 默认脱敏 | 用例 1/8：响应无 doc_number/phone 明文字段 | ✅ |
| 知情同意先行（PIPL §17 / Art.7） | 用例 2/9：consent=false 一律拒绝（422） | ✅ |
| 审计不记内容（Art.30） | 用例 4：iterdump 全文无字段值 | ✅ |
| 可删除/被遗忘（PIPL §47 / Art.17） | 用例 3：物理删除无残留 | ✅ |
| 可导出可携（Art.20） | 用例 1/8：export 回明文且写审计 | ✅ |
| 脱敏输出纪律 | 本文档及所有报告中证件号/手机号仅以 `E1234**78` 形式出现 | ✅ |

## 4. 手工验收路径（UAT 建议）

1. 打开 `http://127.0.0.1:8000/h5/` → 👤 个人主页 → 🪪 出行人资料。
2. 不勾同意书点保存 → 前端拦截提示；勾选后保存 → 列表出现卡片，证件号显示脱敏形。
3. ✏️ 编辑 → 证件号框为空（脱敏形不回填）；改一项保存成功。
4. ⬇️ 导出明文 → 下载 travelers.json，内含明文（本人操作，审计留痕）。
5. 🗑 删除单条 / 清空全部（confirm）→ 卡片消失，刷新后仍为空。
6. 切 🌐 EN → 分区全部英文（含同意书、按钮、toast）。

## 5. 已知边界与说明

- 编辑时证件号必须重填（脱敏形不回填是隐私特性而非缺陷；文案已提示）。
- 密钥文件 `data/.traveler_key` 丢失后旧密文不可解，该行启动时 warning 跳过——用户重录即可（按隐私设计可接受，绝不把密钥入库/入 env）。
- 拥有者上限 20 条出行人；超出返回 422 `too_many_travelers`。
- 导出 JSON 是本人明文数据的唯一出口，前端下载动作对应的 export 调用已在服务端留痕。
