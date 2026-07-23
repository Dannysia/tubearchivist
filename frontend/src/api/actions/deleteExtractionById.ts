import APIClient from '../../functions/APIClient';

const deleteExtractionById = async (extractionId: string) => {
  return APIClient(`/api/download/extraction/${extractionId}/`, {
    method: 'DELETE',
  });
};

export default deleteExtractionById;
