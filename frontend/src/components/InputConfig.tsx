import { useState } from 'react';
import LoadingIndicator from './LoadingIndicator';

type InputTextProps = {
  type: 'text' | 'number';
  name: string;
  value: string | number | null;
  setValue:
    | React.Dispatch<React.SetStateAction<string | null>>
    | React.Dispatch<React.SetStateAction<number | null>>;
  oldValue: string | number | null;
  updateCallback: (arg0: string, arg1: string | boolean | number | null) => void | Promise<void>;
  min?: number;
};

const InputConfig = ({
  type,
  name,
  value,
  setValue,
  oldValue,
  updateCallback,
  min,
}: InputTextProps) => {
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (type === 'number') {
      const inputValue = e.target.value;

      if (inputValue === '') {
        setValue(null);
      } else {
        const numericValue = Number(inputValue);
        (setValue as React.Dispatch<React.SetStateAction<number | null>>)(numericValue);
      }
    } else {
      (setValue as React.Dispatch<React.SetStateAction<string | null>>)(e.target.value);
    }
  };

  const handleUpdate = async (name: string, value: string | boolean | number | null) => {
    setLoading(true);
    setSuccess(false);
    setFailed(false);
    try {
      // awaited, so a rejected update stops reporting itself as saved
      await updateCallback(name, value);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <input type={type} name={name} value={value ?? ''} min={min} onChange={handleChange} />
      <div className="button-box">
        {value !== null && value !== oldValue && (
          <>
            <button onClick={() => handleUpdate(name, value)}>Update</button>
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            <button onClick={() => setValue(oldValue as any)}>Cancel</button>
          </>
        )}
        {oldValue !== null && <button onClick={() => handleUpdate(name, null)}>reset</button>}
        {loading && <LoadingIndicator />}
        {success && <span>✅</span>}
        {failed && <span title="Not saved, the value was rejected">❌</span>}
      </div>
    </div>
  );
};

export default InputConfig;
