//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B8A", "B12"] }],
    output: { bands: 3, sampleType: "UINT8" }
  };
}

function evaluatePixel(sample) {
  return [
    Math.min(255, sample.B12 * 2.5 * 255),
    Math.min(255, sample.B8A * 2.5 * 255),
    Math.min(255, sample.B04 * 2.5 * 255)
  ];
}
