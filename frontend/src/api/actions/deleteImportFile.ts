import APIClient from '../../functions/APIClient';

const deleteImportFile = async (filename: string) => {
  return APIClient(`/api/appsettings/import-file/${encodeURIComponent(filename)}/`, {
    method: 'DELETE',
  });
};

export default deleteImportFile;
