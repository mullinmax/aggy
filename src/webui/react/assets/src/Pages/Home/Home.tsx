import React, { useState, useEffect } from "react";
import FormCategory from "../../Components/Form/FormCategory";
import { checkToken } from "../../utils/checkToken";
import { getCategories } from "../../utils/getCategories";
// import Logo from ".";

export default function Home() {
  const [categories, setCategories] = useState([]);
  const [error, setError] = useState("");
  const [token, setToken] = useState("");

  const fetchCategories = async (token: string) => {
    try {
      const data = await getCategories(token);
      setCategories(data);
    } catch (err) {
      setError("Failed to fetch categories.");
    }
  };
  console.log(categories);

  async function checkForToken() {
    const tokenId = localStorage.getItem("id_token");
    checkToken(tokenId).then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! Status: ${response.status}`);
      } else if (tokenId) {
        console.log(token);
        setToken(tokenId);
        fetchCategories(tokenId);
      }
      return response.json();
    });
  }

  useEffect(() => {
    checkForToken();
  }, [token]);

  // useEffect(() => {
  //   checkForToken();
  //   const fetchCategories = async () => {
  //     try {
  //       const data = await getCategories(token);
  //       setCategories(data);
  //     } catch (err) {
  //       setError("Failed to fetch categories.");
  //     }
  //   };
  //   console.log(categories);
  //   fetchCategories();
  // }, [token]);

  return (
    <div>
      Home Page started
      <div>
        <button onClick={checkForToken}>Check token?</button>
        <FormCategory />
      </div>
    </div>
  );
}
