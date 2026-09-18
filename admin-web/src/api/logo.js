// Normalize browser-supported raster images to PNG for Apple and Google Wallet.
export async function readLogo(file) {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size > 2 * 1024 * 1024) {
    throw new Error("invalidLogo");
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (!image.width || !image.height || image.width > 2048 || image.height > 2048) throw new Error("invalidLogo");
    const canvas = document.createElement("canvas");
    canvas.width = image.width; canvas.height = image.height;
    canvas.getContext("2d").drawImage(image, 0, 0);
    const preview = canvas.toDataURL("image/png");
    const base64 = preview.split(",")[1];
    if (!base64 || base64.length > 2796204) throw new Error("invalidLogo");
    return { base64, preview };
  } catch {
    throw new Error("invalidLogo");
  } finally {
    URL.revokeObjectURL(url);
  }
}
