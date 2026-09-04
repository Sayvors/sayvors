"use client";

import { useState } from "react";

const features = [
  { id: "overall", label: "Overall Experience" },
  { id: "ai", label: "AI Agent Quality" },
  { id: "ui", label: "User Interface" },
  { id: "support", label: "Customer Support" },
  { id: "value", label: "Value for Money" },
];

export default function ProfileRatings() {
  const [ratings, setRatings] = useState<Record<string, number>>({
    overall: 4,
    ai: 5,
    ui: 4,
    support: 5,
    value: 4,
  });
  const [hovered, setHovered] = useState<Record<string, number>>({});

  const handleRate = (featureId: string, stars: number) => {
    setRatings((prev) => ({ ...prev, [featureId]: stars }));
  };

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <h2 className="text-[14px] font-bold text-ink mb-4">Ratings</h2>
      <div className="space-y-3">
        {features.map((feature) => (
          <div key={feature.id} className="flex items-center justify-between">
            <span className="text-[12px] font-medium text-ink">{feature.label}</span>
            <div className="flex items-center gap-0.5">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  onMouseEnter={() => setHovered((prev) => ({ ...prev, [feature.id]: star }))}
                  onMouseLeave={() => setHovered((prev) => ({ ...prev, [feature.id]: 0 }))}
                  onClick={() => handleRate(feature.id, star)}
                  className="transition hover:scale-110"
                >
                  <svg
                    viewBox="0 0 24 24"
                    fill={(hovered[feature.id] || ratings[feature.id]) >= star ? "#f59e0b" : "none"}
                    stroke={(hovered[feature.id] || ratings[feature.id]) >= star ? "#f59e0b" : "#d1d5db"}
                    strokeWidth="1.5"
                    className="h-5 w-5"
                  >
                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
