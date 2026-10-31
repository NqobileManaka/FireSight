"""Train the CNN on synthetic thermal frames and write weights + metrics (artifacts/ai_metrics.json)."""
import json
import os
import time

import numpy as np
import torch
from torch import nn

from app.ai.model import ThermalCNN
from app.ai.synth import dataset
from app.ai.engine import WEIGHTS

torch.manual_seed(7)
xtr, ytr = dataset(1500, seed=1)
xva, yva = dataset(400, seed=2)
xtr, ytr, xva, yva = map(torch.from_numpy, (xtr, ytr, xva, yva))
model, loss_fn = ThermalCNN(), nn.CrossEntropyLoss()
opt = torch.optim.Adam(model.parameters(), 2e-3)
t0 = time.time()
history = []
for epoch in range(10):
    model.train()
    perm = torch.randperm(len(ytr))
    for i in range(0, len(perm), 64):
        idx = perm[i:i + 64]
        opt.zero_grad()
        loss_fn(model(xtr[idx]), ytr[idx]).backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        acc = (model(xva).argmax(1) == yva).float().mean().item()
    history.append(round(acc, 4))
    print(f"epoch {epoch + 1}: val acc {acc:.4f}")
with torch.no_grad():
    pred = model(xva).argmax(1).numpy()
cm = np.zeros((3, 3), int)
for t, p in zip(yva.numpy(), pred):
    cm[t, p] += 1
os.makedirs("artifacts", exist_ok=True)
torch.save(model.state_dict(), WEIGHTS)
json.dump({"dataset": "synthetic thermal frames (app/ai/synth.py); FLAME not available offline",
           "train_samples": len(ytr), "val_samples": len(yva), "val_accuracy": history[-1],
           "accuracy_by_epoch": history, "confusion_matrix": cm.tolist(),
           "classes": ["No Fire", "Fire", "Critical"], "train_seconds": round(time.time() - t0, 1),
           "parameters": sum(p.numel() for p in model.parameters())},
          open("artifacts/ai_metrics.json", "w"), indent=2)
