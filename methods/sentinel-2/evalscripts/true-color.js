//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04"] }],
    output: { bands: 3, sampleType: "UINT8" }
  };
}

function evaluatePixel(sample) {
  return [
    Math.min(255, sample.B04 * 2.5 * 255),
    Math.min(255, sample.B03 * 2.5 * 255),
    Math.min(255, sample.B02 * 2.5 * 255)
  ];
}
