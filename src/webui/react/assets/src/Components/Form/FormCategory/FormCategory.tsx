import React, { useEffect, useState } from "react";
import { addCategory } from "../../../utils/addCategory";
import { checkToken } from "../../../utils/checkToken";
import "./FormCategory.scss";

// interface FormCategoryProps {
//   /** logged in */
//   token: string;
// }

export default function FormCategory() {
  const [category, setCategory] = useState("");
  const [token, setToken] = useState("");
  async function checkForToken() {
    const tokenId = localStorage.getItem("id_token");
    checkToken(tokenId).then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      } else if (tokenId) {
        setToken(tokenId);
      }
      return response.json();
    });
  }

  useEffect(() => {
    checkForToken();
  }, [token]);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setCategory(event.target.value);
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    addCategory(category, token);
  };
  return (
    <div>
      <div className="Form-Category-Container">
        <label htmlFor="category" className="Form-Category-Label">
          Category Title
        </label>
        <input
          type="text"
          id="category"
          value={category}
          className="Category-Form-Input"
          onChange={handleChange}
          name="category"
          placeholder="Add Category"
        />
        <button
          className="Form-Category-Submit"
          type="submit"
          onClick={handleSubmit}
        >
          Add Category
        </button>
      </div>
    </div>
  );
}
