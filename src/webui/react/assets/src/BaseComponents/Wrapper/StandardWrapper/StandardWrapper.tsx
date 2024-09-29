import React, { useState } from "react";
import Login from "../../../Pages/Login";
import Home from "../../../Pages/Home";
import StandardHeader from "../../../BaseComponents/Header/StandardHeader";
import "./StandardWrapper.scss";
import { log } from "console";

interface standardWrapperProps {
  /** logged in */
  loggedIn: boolean;
}

function StandardWrapper({ loggedIn }: standardWrapperProps) {
  const [currentPage, setCurrentPage] = useState("Home");

  // The renderPage method uses a switch statement to render the appropriate current page
  const renderPage = (page: string) => {
    switch (page) {
      case "Login":
        return <Login />;
      default:
        return <Home />;
    }
  };

  console.log(loggedIn);
  return (
    <div>
      <StandardHeader
        loggedIn={loggedIn}
        currentPage={currentPage}
        setCurrentPage={setCurrentPage}
      />
      <div className="Standard-Wrapper">
        {loggedIn ? (
          <div className="Page">{renderPage(currentPage)}</div>
        ) : (
          <Login />
        )}
      </div>
      {/* <Footer></Footer> */}
    </div>
  );
}

export default StandardWrapper;
