import React, { useState } from "react";
import { userLogin } from "../../../utils/userLogin";
import { checkToken } from "../../../utils/checkToken";
import { getCategories } from "../../../utils/getCategories";
import AuthService from "../../../utils/auth";
import "./LoginForm.scss";

export default function LoginForm() {
  const [userFormData, setUserFormData] = useState({
    username: "",
    password: "",
  });

  const loggedIn = AuthService.loggedIn();

  // const [validated] = useState(false);
  // const [showAlert, setShowAlert] = useState(false);

  const handleInputChange = (event: any) => {
    const { name, value } = event.target;
    setUserFormData({ ...userFormData, [name]: value });
  };

  // console.log(getCategories());\

  async function versionResponse() {
    const response = await getCategories();
    console.log(response);
  }

  // versionResponse();

  async function loginFormHandler(event) {
    event.preventDefault();
    userLogin(userFormData)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! Status: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        console.log("Login successful:", data);
        // Store the token or session ID if needed
        const token = data.access_token; // Example: adjust based on actual API response
        // Store token in local storage, session storage, or in-memory
        AuthService.login(token);
        // AuthService(token);
      })
      .catch((error) => {
        console.error("Login failed:", error);
      });
  }

  function logoutHandler() {
    // const token = AuthService.getToken();
    AuthService.logout();
  }

  return (
    <div>
      {loggedIn === false ? (
        <div className="Login-Form-Container">
          <label htmlFor="username" className="Login-Form-Label">
            Username
          </label>
          <input
            type="text"
            id="username"
            className="Login-Form-Input"
            name="username"
            required
            onChange={handleInputChange}
            placeholder="Username"
          />
          <label htmlFor="password" className="Login-Form-Label">
            Password
          </label>
          <input
            type="password"
            id="password"
            className="Login-Form-Input"
            name="password"
            required
            onChange={handleInputChange}
            placeholder="Password"
          />
          <button onClick={loginFormHandler} className="Login-Form-Submit">
            Login
          </button>
        </div>
      ) : (
        <div>
          <button onClick={logoutHandler}>Logout</button>
        </div>
      )}
    </div>
  );
}
