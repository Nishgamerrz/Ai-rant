export type EncodedReferenceImage = {
  imageData: string;
  mimeType: "image/jpeg";
  fileName: string;
};

const MAX_BYTES = 24_000;

export async function encodeFaceReference(file: File): Promise<EncodedReferenceImage> {
  if (!file || !file.type.startsWith("image/")) throw new Error("Choose a valid image file.");
  if (file.size > 20 * 1024 * 1024) throw new Error("Image is larger than 20 MiB.");
  if (typeof createImageBitmap !== "function") throw new Error("This browser cannot resize image references.");
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 512 / Math.max(bitmap.width, bitmap.height));
    let width = Math.max(1, Math.round(bitmap.width * scale));
    let height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", { alpha: false });
    if (!context) throw new Error("Could not prepare the reference image.");
    for (let attempt = 0; attempt < 8; attempt++) {
      canvas.width = width;
      canvas.height = height;
      context.fillStyle = "#fff";
      context.fillRect(0, 0, width, height);
      context.drawImage(bitmap, 0, 0, width, height);
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Image compression failed.")), "image/jpeg", Math.max(0.35, 0.78 - attempt * 0.06));
      });
      if (blob.size <= MAX_BYTES) {
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = "";
        for (let start = 0; start < bytes.length; start += 0x8000) {
          binary += String.fromCharCode(...bytes.subarray(start, Math.min(start + 0x8000, bytes.length)));
        }
        return { imageData: btoa(binary), mimeType: "image/jpeg", fileName: "face-reference.jpg" };
      }
      width = Math.max(96, Math.round(width * 0.82));
      height = Math.max(96, Math.round(height * 0.82));
    }
    throw new Error("Could not compress this image under the 24 KB secure-reference limit.");
  } finally {
    bitmap.close();
  }
}
