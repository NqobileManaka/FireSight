import torch
from torch import nn


class ThermalCNN(nn.Module):
    """Small CNN: 3 conv blocks -> 3-way classifier (No Fire / Fire / Critical) on 64x64 thermal frames."""

    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 8, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(8, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(32 * 8 * 8, 64), nn.ReLU(), nn.Dropout(0.2), nn.Linear(64, 3))

    def forward(self, x):
        return self.head(self.features(x))
