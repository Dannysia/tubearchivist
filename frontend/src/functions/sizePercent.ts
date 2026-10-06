const sizePercent = (originalSize: number, newSize: number) => {
  return `${Math.round((newSize / originalSize) * 100)}%`;
};

export default sizePercent;
