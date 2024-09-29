import React, { useState, useEffect } from "react";
import StandardWrapper from "./BaseComponents/Wrapper/StandardWrapper";
import { checkToken } from "./utils/checkToken";
import { resolve } from "path";

function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  // const loggedIn = AuthService.loggedIn();

  useEffect(() => {
    async function checkForToken() {
      const token = localStorage.getItem("id_token");
      checkToken(token).then((response) => {
        if (!response.ok) {
          setLoggedIn(false);
          // throw new Error(`HTTP error! Status: ${response.status}`);
        } else if (response.ok) {
          setLoggedIn(true);
        }
        return response.json();
      });
    }
    checkForToken();
  }, [loggedIn]);

  return (
    <main>
      <StandardWrapper loggedIn={loggedIn} />
    </main>
  );
}

export default App;
