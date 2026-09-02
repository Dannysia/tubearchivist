type ChannelYouTubeLinkProps = {
  channelId: string;
  channelname: string;
};

const ChannelYouTubeLink = ({ channelId, channelname }: ChannelYouTubeLinkProps) => {
  return (
    <a
      className="link-button"
      href={`https://www.youtube.com/channel/${channelId}`}
      target="_blank"
      rel="noopener noreferrer"
      title={`View ${channelname} on YouTube`}
    >
      View on YouTube
    </a>
  );
};

export default ChannelYouTubeLink;
