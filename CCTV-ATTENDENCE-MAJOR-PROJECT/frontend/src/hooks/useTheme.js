
import { useState, useEffect } from 'react';

const useTheme = () => {
  const [theme, setTheme] = useState('light');

  useEffect(() => {
    document.body.classList.remove('dark');
    localStorage.setItem('theme', 'light');
  }, []);

  const toggleTheme = () => {
    setTheme('light');
  };

  return { theme, toggleTheme };
};

export default useTheme;
