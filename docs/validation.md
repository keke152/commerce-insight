# v1.1.0 验证记录

验证日期：2026-10-28。

## 本地自动化

- Windows / Python 3.10；按 `requirements-dev.txt` 安装依赖。
- `python -m unittest discover -s tests -v`：27项通过。
- `node --check static/app.js`：通过。
- `git diff --check`：通过。
- 模型96条训练、24条独立虚构测试，当前Accuracy及Macro-F1均为1.0。样例小且简单，不作为真实业务指标。

## 浏览器流程

Headless Microsoft Edge 真实请求本地FastAPI服务，验证：

1. 订单下一页与搜索。
2. 商品名称实际模型推断。
3. 中文CSV预检。
4. 未确认授权时无法提交。
5. 导入后240条变246条。
6. 相同文件再次导入仍为246条。
7. 人工复核保存后页面标识更新。
8. HTML报告返回内容。
9. CSV导出包含全部订单。
10. 920px和390px视口无页面级横向溢出。

控制台无页面脚本错误；工作台没有外部资源请求。重新运行同一流程仍通过。数据库为独立的虚构验收库，未使用商家实际数据。

## 尚未验证

MySQL端到端运行、真实平台连接、真实业务模型效果、多人并发性能与生产鉴权。CI运行状态请以GitHub Actions为准，本记录不预先声称CI结果。
