"""Offline product classifier; demo evaluation is deliberately separated from training."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score

CATEGORIES = ("食品饮料", "美妆个护", "家居生活", "数码配件", "母婴用品", "其他")
MODEL_VERSION = "char-tfidf-lr-v1"


@lru_cache(maxsize=1)
def model():
    corpus = json.loads((Path(__file__).parent / "data" / "catalog.json").read_text(encoding="utf-8"))
    train, test = [], []
    for category, samples in corpus.items():
        train.extend((text, category) for text in samples["train"])
        test.extend((text, category) for text in samples["test"])
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(1, 3), sublinear_tf=True)
    x = vectorizer.fit_transform([item[0] for item in train])
    classifier = LogisticRegression(C=8, max_iter=500, random_state=42)
    classifier.fit(x, [item[1] for item in train])
    predicted = classifier.predict(vectorizer.transform([item[0] for item in test]))
    report = {
        "version": MODEL_VERSION, "algorithm": "字符 TF-IDF + Logistic Regression",
        "training_count": len(train), "test_count": len(test), "categories": list(CATEGORIES),
        "accuracy": round(float(accuracy_score([item[1] for item in test], predicted)), 4),
        "macro_f1": round(float(f1_score([item[1] for item in test], predicted, average="macro")), 4),
        "dataset_kind": "人工编写的虚构商品目录；训练集与测试集分开",
        "limitations": "小样本演示评测，不代表真实平台准确率；模型分值未经概率校准。人工复核不会自动重训。",
    }
    return vectorizer, classifier, report


@lru_cache(maxsize=4096)
def predict(product_name: str) -> dict:
    vectorizer, classifier, _ = model()
    vector = vectorizer.transform([product_name.strip().lower()])
    if not vector.nnz:
        return {"category": "其他", "score": 0.0, "needs_review": True,
                "reason": "没有识别到已学习的文本特征，请人工复核", "source": MODEL_VERSION}
    scores = classifier.predict_proba(vector)[0]
    ranking = np.argsort(scores)[::-1]
    best, second = int(ranking[0]), int(ranking[1])
    score = float(scores[best])
    category = str(classifier.classes_[best])
    contribution = vector.toarray()[0] * classifier.coef_[best]
    names = vectorizer.get_feature_names_out()
    features = [str(names[i]) for i in np.argsort(contribution)[::-1] if contribution[i] > 0 and len(names[i]) >= 2][:3]
    needs_review = score < .55 or score - float(scores[second]) < .15 or category == "其他"
    return {"category": category, "score": round(score, 4), "needs_review": needs_review,
            "reason": "本地文本模型；主要特征：" + ("、".join(features) or "字符组合") + ("；建议人工复核" if needs_review else ""),
            "source": MODEL_VERSION}


def classify(product_name: str) -> tuple[str, float, str]:
    result = predict(product_name)
    return result["category"], result["score"], result["reason"]
