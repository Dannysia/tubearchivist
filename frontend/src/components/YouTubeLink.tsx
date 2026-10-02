type YouTubeLinkProps = {
  path: string;
  title: string;
};

const YouTubeLink = ({ path, title }: YouTubeLinkProps) => {
  return (
    <a
      className="link-button"
      href={`https://www.youtube.com/${path}`}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
    >
      View on YouTube
    </a>
  );
};

export default YouTubeLink;
