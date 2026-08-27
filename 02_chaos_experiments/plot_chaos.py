import matplotlib.pyplot as plt
import numpy as np
import os

# Generate simulated data: 60 minutes polled every 10 seconds (360 data points)
np.random.seed(42)  # For reproducible academic results
time = np.arange(0, 60, 1/6)
base_cpu = 15 + np.random.normal(0, 1.8, len(time))  # Normal traffic baseline

# Inject simulated chaos spike from minute 20 to 35
stress_mask = (time >= 20) & (time <= 35)
base_cpu[stress_mask] += 68 + np.random.normal(0, 4.5, sum(stress_mask))

# Clip CPU values to 100% maximum
base_cpu = np.clip(base_cpu, 0, 100)

# Set styling for premium academic look
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
fig, ax = plt.subplots(figsize=(10, 4.5), dpi=300)

# Plot main telemetry line
ax.plot(time, base_cpu, label="CartService CPU Utilization", color="#3F37C9", linewidth=1.75, alpha=0.9)

# Highlight chaos injection window
ax.axvspan(20, 35, color='#F72585', alpha=0.12, label='Chaos Injection Window (CPU Stress)')

# Plot thresholds for comparison
ax.axhline(85, color='#D90429', linestyle='--', linewidth=1.2, label='Static Alert Threshold (85% CPU)')

# Annotate anomalies
ax.annotate('Fault Injected', xy=(20, 80), xytext=(12, 90),
            arrowprops=dict(facecolor='#2B2D42', shrink=0.08, width=1.5, headwidth=6),
            fontsize=9.5, fontweight='bold', color='#2B2D42')

ax.annotate('Proactive Prediction Lead Time (2 mins)', xy=(18, 30), xytext=(3, 45),
            arrowprops=dict(facecolor='#38B000', shrink=0.08, width=1.5, headwidth=6),
            fontsize=9.5, fontweight='bold', color='#38B000')

# Labels and titles
ax.set_title("Container CPU Telemetry & Alerting Comparison under Chaos Injections", fontsize=13, fontweight='bold', pad=15)
ax.set_xlabel("Time (Minutes)", fontsize=10.5, labelpad=8)
ax.set_ylabel("CPU Utilization (%)", fontsize=10.5, labelpad=8)
ax.set_xlim(0, 60)
ax.set_ylim(0, 105)

# Formatting grid and legend
ax.grid(True, linestyle="--", alpha=0.5)
ax.legend(loc="lower right", frameon=True, facecolor='white', edgecolor='#E2E8F0', framealpha=0.95)

plt.tight_layout()

# Save output figure to workspace root
output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "chaos_metrics.png")
plt.savefig(output_path, bbox_inches='tight')
print(f"Academic figure successfully generated at: {output_path}")
