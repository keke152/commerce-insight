# 商品分类模型说明

## 模型

- 版本：`char-tfidf-lr-v1`。
- 特征：scikit-learn `TfidfVectorizer(analyzer="char", ngram_range=(1,3), sublinear_tf=True)`。
- 分类器：`LogisticRegression(C=8, max_iter=500, random_state=42)`。
- 类别：食品饮料、美妆个护、家居生活、数码配件、母婴用品、其他。
- 首次使用时本地训练，进程内缓存；没有网络模型调用、自动下载或第三方模型文件反序列化。

## 数据和评测

`data/catalog.json` 由人工编写，每类16个训练商品、4个测试商品，总计96训练/24测试。先按固定字段分离，再只使用训练文本拟合词表、IDF和分类器；测试文本不参与拟合。

`GET /api/model` 返回实际计算的 Accuracy 与 Macro-F1。当前样例简单且与训练文本相似，可能得到满分；这只能证明该小样本流程可复现，不能推断平台线上准确率。没有独立真实数据、时间外验证、复杂长尾/多商品订单测试或概率校准。

## 解释与人工复核

按当前文本的 TF-IDF 与目标类别系数乘积，取正贡献的前3个至少双字符片段作解释。解释反映特征贡献，不是因果解释。

分值低于0.55、第一第二类别差小于0.15、判为其他或没有已学习特征时，提示人工复核。数值虽来自 `predict_proba`，本项目没有校准验证，因此界面称“模型分值”，不承诺实际正确概率。

人工复核存于独立表，不覆盖原结果，也不自动加入训练。下一步应审查标注质量，再离线训练并用未参与优化的真实测试集评估。

## 参考

- [scikit-learn 文本特征提取](https://scikit-learn.org/stable/modules/feature_extraction.html#text-feature-extraction)
- [LogisticRegression 参数与接口](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)
