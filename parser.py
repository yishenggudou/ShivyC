"""The ShivyC parser. It's written entirely by hand because automatic parser
generators are no fun.

"""
from collections import namedtuple

import ast
from errors import CompilerError
import errors
from tokens import Token
import token_kinds

class Parser:
    """Provides the parser functionality to convert a list of tokens into an
    AST.

    Each internal function expect_* corresponds to a unique non-terminal symbol
    in the C grammar. It parses the given tokens beginning at the given index to
    try to match a grammar rule that generates the desired symbol. If a match is
    found, it returns a tuple (Node, index) where Node is an AST node for that
    match and index is one more than that of the last token consumed in that
    parse.  If no match is not found, returns (None, 0) and saves the potential
    error to the errors variable.

    errors (List[Tuple[CompilerError, int]]) - Stores a list of compiler errors
    for each time a potential parsing path failed, and the index at which that
    error occurred. If the parse is unsuccessful, we will raise the
    CompilerError that successfully parsed the most tokens.

    """
    def __init__(self):
        self.errors = []

    def parse(self, tokens):
        """Parse the provided list of tokens into an abstract syntax tree (AST)

        tokens (List[Token]) - A list of the tokens, as generated by the lexer
        returns (Node) - The root node of the generated AST"""

        node, index = self.expect_main(tokens, 0)
        if not node:
            # Parsing failed, so we return the error that was most successsful
            # at parsing. If multiple errors parsed the same number of tokens,
            # return the one added later.
            raise sorted(self.errors, key=lambda error: error[1])[-1][0]

        # Ensure there's no tokens left at after the main function
        if tokens[index:]:
            raise self.make_error("unexpected token", index, tokens, self.AT)
        return node

    def expect_main(self, tokens, index):
        """Ex: int main() { return 4; } """

        kinds_before = [token_kinds.int_kw, token_kinds.main,
                        token_kinds.open_paren, token_kinds.close_paren,
                        token_kinds.open_brack]
        match_start = self.match_tokens(tokens[index:], kinds_before)
        if match_start:
            index += match_start
        else:
            err = "expected main function starting"
            return self.add_error(err, index, tokens, self.AT)

        nodes = []
        while True:
            node, new_index = self.expect_statement(tokens, index)
            
            if not node:
                node, new_index = self.expect_declaration(tokens, index)
                if not node: break                

            index = new_index
            nodes.append(node)

        if self.match_token(tokens[index:], token_kinds.close_brack):
            index += 1
        else:
            err = "expected closing brace"
            return self.add_error(err, index, tokens, self.GOT)
        return (ast.MainNode(nodes), index)

    def expect_statement(self, tokens, index):
        node, new_index = self.expect_return(tokens, index)
        if node: return (node, new_index)

        node, new_index = self.expect_expr_statement(tokens, index)
        if node: return (node, new_index)

        return (None, 0)

    def expect_semicolon(self, node, tokens, index):
        """Expect a semicolon at tokens[index]. If one is found, returns
        (node, index + 1). Otherwise, returns (None, 0) and adds an error.
        """
        if self.match_token(tokens[index:], token_kinds.semicolon):
            return (node, index + 1)
        else:
            err = "expected semicolon"
            return self.add_error(err, index, tokens, self.AFTER)
        
    def expect_return(self, tokens, index):
        if self.match_token(tokens[index:], token_kinds.return_kw):
            index += 1
        else:
            err = "expected return keyword"
            return self.add_error(err, index, tokens, self.GOT)

        node, index = self.expect_expression(tokens, index)
        if not node: return (None, 0)

        return self.expect_semicolon(ast.ReturnNode(node), tokens, index)

    def expect_expr_statement(self, tokens, index):
        """Try to parse an expression, and also expect a semicolon after what
        was parsed."""
        node, index = self.expect_expression(tokens, index)
        if not node: return (None, 0)

        return self.expect_semicolon(ast.ExprStatementNode(node), tokens,
                                     index)
    
    def expect_expression(self, tokens, index):
        """Implemented as a shift-reduce parser. Tries to comprehend as much as
        possible of tokens past index as being an expression, and the index
        returned is the first token that could not be parsed into the
        expression. If literally none of it could be parsed as an expression,
        returns (None, 0) like usual.

        """
                
        # Dictionay of key-value pairs {TokenKind: precedence} where higher
        # precedence is higher.
        binary_operators = {token_kinds.plus: 11,
                            token_kinds.star: 12,
                            token_kinds.equals: 1}

        # The set of assignment_tokens (because these are right-associative)
        assignment_operators = {token_kinds.equals}

        # An item in the parsing stack. The item is either a Node or Token,
        # where the node must generate an expression, and the length is the
        # number of tokens consumed in generating this node.
        StackItem = namedtuple("StackItem", ['item', 'length'])
        stack = []

        # TODO: clean up  the if-statements here
        i = index
        while True:
            # If the top of the stack is a number, reduce it to an expression
            # node
            if (stack and isinstance(stack[-1].item, Token)
                and stack[-1].item.kind == token_kinds.number):
                stack[-1] = StackItem(ast.NumberNode(stack[-1].item), 1)
            
            # If the top of the stack is an identifier, reduce it to
            # an identifier node
            elif (stack and isinstance(stack[-1].item, Token)
                and stack[-1].item.kind == token_kinds.identifier):
                stack[-1] = StackItem(ast.IdentifierNode(stack[-1].item), 1)
            
            # If the top of the stack matches a binary operator, reduce it to an
            # expression node. TODO(shivam): check precedence of next operator
            elif (len(stack) >= 3
                  and isinstance(stack[-1].item, ast.Node)
                  and isinstance(stack[-2].item, Token)
                  and stack[-2].item.kind in binary_operators.keys()
                  and isinstance(stack[-3].item, ast.Node)

                  # Make sure next token is not higher precedence
                  and not (i < len(tokens)
                           and tokens[i].kind in binary_operators.keys()
                           and (binary_operators[tokens[i].kind] >
                                binary_operators[stack[-2].item.kind]))
                  
                  # Make sure this and next token are not both assignment
                  # tokens, because assignment tokens are right associative.
                  and not (i < len(tokens)
                           and stack[-2].item.kind in assignment_operators
                           and tokens[i].kind in assignment_operators)):
                left_expr = stack[-3]
                right_expr = stack[-1]
                operator = stack[-2]

                # Remove these last 3 elements
                del stack[-3:]
                stack.append(
                    StackItem(ast.BinaryOperatorNode(left_expr.item,
                                                     operator.item,
                                                     right_expr.item),
                              left_expr.length + operator.length +
                              right_expr.length))
            else:
                # If we're at the end of the token list, or we've reached a
                # token that can never appear in an expression, stop reading.
                # Note we must update this every time the parser is expanded to
                # accept more identifiers.
                if i == len(tokens): break
                elif (tokens[i].kind != token_kinds.number
                      and tokens[i].kind != token_kinds.identifier
                      and tokens[i].kind not in binary_operators.keys()): break
                
                stack.append(StackItem(tokens[i], 1))
                i += 1

        if stack and isinstance(stack[0].item, ast.Node):
            return (stack[0].item, index + stack[0].length)
        else:
            return self.add_error("expected expression", index, tokens,
                                  self.GOT)
        
    def expect_declaration(self, tokens, index):
        if self.match_token(tokens[index:], token_kinds.int_kw):
            index += 1
        else:
            err = "expected type name"
            return self.add_error(err, index, tokens, self.GOT)

        if self.match_token(tokens[index:], token_kinds.identifier):
            variable_name = tokens[index]
            index += 1
        else:
            err = "expected identifier"
            return self.add_error(err, index, tokens, self.AFTER)

        return self.expect_semicolon(ast.DeclarationNode(variable_name), tokens,
                                     index)

    #
    # Utility functions for the parser
    #
    def match_token(self, tokens, kind_expected):
        return self.match_tokens(tokens, [kind_expected])
    
    def match_tokens(self, tokens, kinds_expected):
        """Checks if the provided tokens match the expected token kinds, in
        order. If the tokens all have the expected kind, returns the length of
        kinds_expected. Otherwise, returns 0.

        tokens (List[Token]) - A list of tokens
        expected (List[TokenKind, None]) - A list of token kinds to expect

        """
        if len(tokens) < len(kinds_expected): return False
        if all(kind == token.kind for kind, token
               in zip(kinds_expected, tokens)):
            return len(kinds_expected)
        else: return 0

    # AT generates a message like "expected semicolon at '}'", GOT generates a
    # message like "expected semicolon, got '}'", and AFTER generates a message
    # like "expected semicolon after '15'" (if possible).
    #
    # As a very general guide, use AT when a token should be removed, use AFTER
    # when a token should be to be inserted (esp. because of what came before),
    # and GOT when a token should be changed.
    AT = 1
    GOT = 2
    AFTER = 3 
    def add_error(self, message, index, tokens, message_type):
        """Generates a CompilerError and adds it to the list of errors at the
        given index. For convenience, also returns (None, 0)

        message (str) - the base message to put in the error
        tokens (List[Token]) - a list of tokens
        index (int) - the index of the offending token
        message_type (int) - either self.AT, self.GOT, or self.AFTER. 
        returns - (None, 0)

        """
        self.errors.append(
            (self.make_error(message, index, tokens, message_type),
             index))
        return (None, 0)
        
    def make_error(self, message, index, tokens, message_type):
        """Generate a CompilerError. 

        message (str) - the base message to put in the error
        tokens (List[Token]) - a list of tokens
        index (int) - the index of the offending token
        message_type (enum) - either self.AT, self.GOT, or self.AFTER.

        """
        if len(tokens) == 0:
            return CompilerError("{} at beginning of source".format(message))

        # If the index is too big, we're always using the AFTER form
        if index >= len(tokens):
            index = len(tokens)
            message_type = self.AFTER
        # If the index is too small, we should not use the AFTER form
        elif index <= 0:
            index = 0
            if message_type == self.AFTER: message_type = self.GOT

        if message_type == self.AT:
            return errors.token_error("{} at '{{}}'".format(message),
                                      tokens[index])
        elif message_type == self.GOT:
            return errors.token_error("{}, got '{{}}'".format(message),
                                      tokens[index])
        elif message_type == self.AFTER:
            return errors.token_error("{} after '{{}}'".format(message),
                                      tokens[index-1])
        else:
            raise ValueError("Unknown error message type")
